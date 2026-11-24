"use strict";

// Read GitHub lockfiles that have already been pinned. Only registry metadata is fetched.
const fs = require("node:fs");
const path = require("node:path");
const {createHash} = require("node:crypto");
const {gzipSync} = require("node:zlib");

const [modulesDir, inputs, destination] = process.argv.slice(2);
if (!modulesDir || !inputs || !destination) {
  throw new Error("usage: node npm_query_prepare.cjs NPM_NODE_MODULES RAW_LOCK_ROOT OUTPUT");
}
const bundled = (name) => require(path.join(path.resolve(modulesDir), name));
const semver = bundled("semver");
const Arborist = bundled("@npmcli/arborist");
const libraryVersions = {
  semver: bundled("semver/package.json").version,
  arborist: bundled("@npmcli/arborist/package.json").version,
};
if (libraryVersions.semver !== "7.8.1" || libraryVersions.arborist !== "9.7.0") {
  throw new Error("use the registered semver and Arborist versions");
}
const pins = JSON.parse(fs.readFileSync(path.join(__dirname, "npm-query-pins.json")));
const digest = (algorithm, content) => createHash(algorithm).update(content).digest("hex");
const cache = path.join(inputs, "packuments");
fs.mkdirSync(cache, {recursive: true});

function stable(version) {
  return typeof version === "string" && semver.valid(version) && semver.prerelease(version) === null;
}

function legalNode(node) {
  return (
    node.location.startsWith("node_modules/") &&
    !node.isLink && !node.inBundle &&
    /^https:\/\/registry\.npmjs\.org\//.test(node.resolved || "") &&
    stable(node.version) &&
    (node.package.name === undefined || node.package.name === node.name)
  );
}

function ordinary(edge) {
  return edge.type === "prod" && edge.to && edge.to !== edge.from &&
    edge.name === edge.to.name && semver.validRange(edge.spec) !== null;
}

async function planSnapshot(pin) {
  const folder = path.join(inputs, pin.repo.replace("/", "--"));
  const raw = fs.readFileSync(path.join(folder, "package-lock.json"));
  const version = JSON.parse(raw).lockfileVersion;
  if (version !== 2 && version !== 3) throw new Error("the frozen sample requires lockfile v2/v3");
  const tree = await new Arborist({path: folder}).loadVirtual();
  const nodes = new Map([...tree.inventory.values()].filter(legalNode).map(ast => [ast.location, ast]));
  const adjacency = new Map([...nodes.keys()].map(u => [u, new Set()]));
  const edges = [];
  for (const u of [...nodes.keys()].sort()) {
    for (const edge of nodes.get(u).edgesOut.values()) {
      if (!ordinary(edge) || !nodes.has(edge.to.location)) continue;
      const v = edge.to.location;
      adjacency.get(u).add(v);
      adjacency.get(v).add(u);
      edges.push([u,v,edge.name,edge.spec]);
    }
  }
  edges.sort((a,b) => JSON.stringify(a).localeCompare(JSON.stringify(b), "en"));
  const candidates = [...adjacency].filter(([_,neighbors]) => neighbors.size >= 2)
    .map(([u]) => [digest("sha256", pin.repo + "\n" + u),u]).sort();
  const roster = [];
  const used = new Set();
  let duplicates = 0;
  for (const [_,center] of candidates.slice(0,12)) {
    const queue = [[center,0]];
    const visits = new Set([center]);
    for (let i=0;i<queue.length;i++) {
      const [u,d] = queue[i];
      if (d===2) continue;
      for (const v of [...adjacency.get(u)].sort()) {
        if (visits.has(v) || visits.size===12) continue;
        visits.add(v);
        queue.push([v,d+1]);
      }
    }
    const locations = [...visits].sort();
    const included = edges.filter(([u,v]) => visits.has(u) && visits.has(v));
    const key = JSON.stringify([locations,included]);
    if (used.has(key)) {
      duplicates++;
      continue;
    }
    used.add(key);
    roster.push({center,locations,edges:included});
  }
  const header = Buffer.from("blob "+raw.length+"\0","ascii");
  return {
    pin, nodes, roster,
    metadata: {repo:pin.repo,sha:pin.sha,lockfileVersion:version,
      lock_sha256:digest("sha256",raw),
      git_blob:digest("sha1",Buffer.concat([header,raw])),
      inventory:tree.inventory.size,legal: nodes.size,
      ordinary_edges: edges.length,
      selected_anchors:Math.min(candidates.length,12),duplicate_neighborhoods:duplicates},
  };
}

async function loadPackument(name) {
  const file = path.join(cache,digest("sha256",name)+".json");
  if (!fs.existsSync(file)) {
    let problem;
    for (let attempt=0;attempt<3;attempt++) {
      try {
        const response=await fetch("https://registry.npmjs.org/"+encodeURIComponent(name),
                                   {signal:AbortSignal.timeout(35000)});
        if (!response.ok) throw new Error(String(response.status));
        const raw=Buffer.from(await response.arrayBuffer());
        JSON.parse(raw);
        fs.writeFileSync(file,raw);
        problem=null;
        break;
      } catch (error) {
        problem=error;
      }
    }
    if (problem) throw new Error("could not verify registry metadata for "+name+": "+problem.message);
  }
  const raw=fs.readFileSync(file);
  const info=JSON.parse(raw);
  if(info.name!==name || !info.versions || !info.time) throw new Error("unexpected registry object "+name);
  return {info,sha:digest("sha256",raw)};
}

function versionsAt(info, observed, cutoff) {
  const maximum=Date.parse(cutoff);
  const eligible=Object.keys(info.versions).filter(v=>stable(v) && semver.major(v)===semver.major(observed)
    && Number.isFinite(Date.parse(info.time[v])) && Date.parse(info.time[v])<=maximum).sort(semver.compare);
  const actual=eligible.indexOf(observed);
  if (actual<0) return null;
  const start=16*Math.floor(actual/16);
  return eligible.slice(start,start+16);
}

function auditedRange(manifest, name) {
  if (manifest.optionalDependencies && Object.hasOwn(manifest.optionalDependencies,name)) return null;
  return manifest.dependencies && Object.hasOwn(manifest.dependencies,name) ? manifest.dependencies[name] : null;
}

async function run() {
  const frozen=[];
  for (const pin of pins) frozen.push(await planSnapshot(pin));
  const names=[...new Set(frozen.flatMap(s=>s.roster.flatMap(t=>t.locations.map(u=>s.nodes.get(u).name))))].sort();
  const catalogs=new Map();
  let cursor=0;
  await Promise.all([...Array(12)].map(async ()=>{
    while(cursor<names.length) {
      const name=names[cursor++];
      catalogs.set(name,await loadPackument(name));
    }
  }));
  const cases=[];
  for (const snapshot of frozen) {
    const {pin,nodes,roster,metadata}=snapshot;
    const available=new Map();
    for (const loc of new Set(roster.flatMap(t=>t.locations))) {
      const node=nodes.get(loc);
      const {info}=catalogs.get(node.name);
      available.set(loc,versionsAt(info,node.version,pin.cutoff));
    }
    metadata.missing_catalog_tasks=0;
    metadata.unrepresentable_edges=0;
    metadata.literal_range_tests=0;
    metadata.distinct_range_tests=0;
    for (const task of roster) {
      if(task.locations.some(v=>!available.get(v))){
        metadata.missing_catalog_tasks++;
        continue;
      }
      const ids=new Map(task.locations.map((v,i)=>[v,String(i).padStart(2,"0")]));
      const vertices=task.locations.map(loc=>{
        const node=nodes.get(loc);
        return {id:ids.get(loc),path:loc,name:node.name,versions:available.get(loc),actual:node.version};
      });
      const relations=[];
      for (const [from,to,name,spec] of task.edges) {
        const {info}=catalogs.get(nodes.get(from).name);
        const ranges=available.get(from).map(v=>auditedRange(info.versions[v],name));
        if(ranges.some(r=>r!==null && (typeof r!=="string" || semver.validRange(r)===null))) {
          metadata.unrepresentable_edges++;
          continue;
        }
        // 0 = undeclared ordinary dependency, 1 = range accepts, 2 = range rejects.
        const children=available.get(to);
        const unique=new Map();
        for (const r of new Set(ranges)) {
          unique.set(r, r===null?"0".repeat(children.length):
            children.map(v=>semver.satisfies(v,r)?"1":"2").join(""));
        }
        metadata.literal_range_tests+=ranges.filter(r=>r!==null).length*children.length;
        metadata.distinct_range_tests+=(unique.size-Number(unique.has(null)))*children.length;
        const grid=ranges.map(r=>unique.get(r));
        relations.push({from:ids.get(from),to:ids.get(to),original_range:spec,ranges,grid});
      }
      cases.push({repo:pin.repo,center:task.center,vertices,relations});
    }
    console.log(JSON.stringify(metadata));
  }
  fs.mkdirSync(destination,{recursive:true});
  fs.writeFileSync(path.join(destination,"npm-query-fixtures.json.gz"),gzipSync(JSON.stringify(cases)+"\n"));
  const manifest={libraries:libraryVersions,locks:frozen.map(s=>s.metadata),
    packuments:Object.fromEntries(names.map(n=>[n,catalogs.get(n).sha]))};
  fs.writeFileSync(path.join(destination,"npm-query-source.json"),JSON.stringify(manifest,null,2)+"\n");
  console.log(JSON.stringify({tasks:cases.length,packuments:names.length}));
}

run().catch(error=>{
  console.error(error);
  process.exitCode=1;
});
