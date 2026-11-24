"use strict";

// Verify each frozen table cell with node-semver Range.test.
// Optional raw archives also prove snapshot identity, dependency locations and candidate bands.
const fs=require("node:fs");
const path=require("node:path");
const {createHash}=require("node:crypto");
const {gunzipSync}=require("node:zlib");
const assert=require("node:assert/strict");
const [modulesDir,fixtureFile,manifestFile,rawFolder]=process.argv.slice(2);
if(!modulesDir || !fixtureFile || !manifestFile){
  throw new Error("usage: node npm_query_verify.cjs NPM_NODE_MODULES FIXTURES MANIFEST [RAW_ARCHIVES]");
}
const semver=require(path.join(path.resolve(modulesDir),"semver"));
const v=require(path.join(path.resolve(modulesDir),"semver/package.json")).version;
const manifest=JSON.parse(fs.readFileSync(manifestFile));
assert.equal(v,manifest.libraries.semver);
const pins=Object.fromEntries(JSON.parse(fs.readFileSync(path.join(__dirname,"npm-query-pins.json"))).map(p=>[p.repo,p]));
const terms=JSON.parse(gunzipSync(fs.readFileSync(fixtureFile)));
const digest=(content)=>createHash("sha256").update(content).digest("hex");
const rawLocks=new Map();
const inventories=new Map();

if(rawFolder){
  for(const row of manifest.locks){
    const bytes=fs.readFileSync(path.join(rawFolder,row.repo.replace("/","--"),"package-lock.json"));
    assert.equal(digest(bytes),row.lock_sha256);
    const blob=createHash("sha1").update("blob "+bytes.length+"\0").update(bytes).digest("hex");
    assert.equal(blob,row.git_blob);
    assert.equal(row.sha,pins[row.repo].sha);
    rawLocks.set(row.repo,JSON.parse(bytes).packages);
  }
  for(const [name,sha] of Object.entries(manifest.packuments)){
    const bytes=fs.readFileSync(path.join(rawFolder,"packuments",digest(name)+".json"));
    assert.equal(digest(bytes),sha);
    inventories.set(name,JSON.parse(bytes));
  }
}

function resolveAt(records,pathname,dependency){
  for(let current=pathname;;){
    const candidate=(current ? current+"/" : "")+"node_modules/"+dependency;
    if(Object.hasOwn(records,candidate)) return candidate;
    if(!current)return null;
    const p=current.lastIndexOf("/node_modules/");
    current=p<0?"":current.substring(0,p);
  }
}

let cells=0,edges=0,localVersions=0;
const quantities={undeclared:0,accepted:0,rejected:0};
for(const task of terms){
  const zones=Object.fromEntries(task.vertices.map(row=>[row.id,row]));
  for(const u of task.vertices){
    assert.ok(u.versions.includes(u.actual));
    assert.ok(u.versions.length>=1 && u.versions.length<=16);
    assert.ok(u.versions.every(v=>semver.prerelease(v)===null && semver.major(v)===semver.major(u.actual)));
    if(rawFolder){
      assert.equal(rawLocks.get(task.repo)[u.path].version,u.actual);
      const info=inventories.get(u.name);
      const cutoff=Date.parse(pins[task.repo].cutoff);
      const stable=Object.keys(info.versions).filter(version=>{
        const p=semver.parse(version);
        return p && !p.prerelease.length && p.major===semver.major(u.actual) && Date.parse(info.time[version])<=cutoff;
      }).sort(semver.compare);
      const from=Math.floor(stable.indexOf(u.actual)/16)*16;
      assert.ok(from>=0);
      assert.deepEqual(stable.slice(from,from+16),u.versions);
      localVersions++;
    }
  }
  for(const edge of task.relations){
    const src=zones[edge.from],dst=zones[edge.to];
    if(rawFolder){
      const lock=rawLocks.get(task.repo);
      assert.equal(resolveAt(lock,src.path,dst.name),dst.path);
      assert.ok(semver.validRange(lock[src.path].dependencies[dst.name])!==null);
      assert.ok(!Object.hasOwn(lock[src.path].optionalDependencies||{},dst.name));
      const pack=inventories.get(src.name);
      for(const [i,v] of src.versions.entries()){
        const current=pack.versions[v];
        const expected=Object.hasOwn(current.optionalDependencies||{},dst.name)
          ? null : current.dependencies?.[dst.name] ?? null;
        assert.equal(edge.ranges[i],expected);
      }
    }
    assert.equal(edge.ranges.length,src.versions.length);
    assert.equal(edge.grid.length,src.versions.length);
    for(const [i,r] of edge.ranges.entries()){
      const check=r===null?null:new semver.Range(r);
      assert.equal(edge.grid[i],dst.versions.map(v=>check===null?"0":check.test(v)?"1":"2").join(""));
      cells+=dst.versions.length;
    }
    const code=edge.grid[src.versions.indexOf(src.actual)][dst.versions.indexOf(dst.actual)];
    quantities[["undeclared","accepted","rejected"][Number(code)]]++;
    edges++;
  }
}
console.log(JSON.stringify({verified_cells:cells,directed_edges:edges,raw_inventory_positions:localVersions,observed:quantities}));
