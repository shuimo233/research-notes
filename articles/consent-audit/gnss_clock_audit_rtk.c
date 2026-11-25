/* RTKLIB v2.4.3-b34 adapter for GPS L1 predictions and standard point fixes. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rtklib.h"

static nav_t navigation;

static const eph_t *nearest_gps(gtime_t when, int satellite)
{
    const eph_t *found = NULL;
    double allowable = MAXDTOE + 1.0;
    for (int i = 0; i < navigation.n; ++i) {
        const eph_t *eph = navigation.eph + i;
        if (eph->sat != satellite) continue;
        const double gap = fabs(timediff(when, eph->toe));
        if (gap <= allowable) {
            allowable = gap;
            found = eph;
        }
    }
    return found;
}

static int predict_rows(void)
{
    int id, week, prn;
    double tow, receiver[3];
    while (scanf("%d %d %lf %d %lf %lf %lf", &id, &week, &tow, &prn,
                 receiver, receiver + 1, receiver + 2) == 7) {
        const gtime_t received = gpst2time(week, tow);
        const eph_t *eph = nearest_gps(received, satno(SYS_GPS, prn));
        if (!eph || eph->svh) {
            printf("%d unavailable\n", id);
            continue;
        }
        double sat[3], clock = 0.0, variance = 0.0, ray[3];
        gtime_t sent = timeadd(received, -0.075);
        double range = 0.0;
        for (int step = 0; step < 3; ++step) {
            eph2pos(sent, eph, sat, &clock, &variance);
            range = geodist(sat, receiver, ray);
            sent = timeadd(received, -range / CLIGHT);
        }
        eph2pos(sent, eph, sat, &clock, &variance);
        range = geodist(sat, receiver, ray);
        double lla[3], angles[2];
        ecef2pos(receiver, lla);
        satazel(lla, ray, angles);
        const double water = tropmodel(received, lla, angles, 0.7);
        const double ion = ionmodel(received, navigation.ion_gps, lla, angles);
        const double nominal = range - CLIGHT * (clock - eph->tgd[0]) + ion + water;
        printf("%d %.7f %.8f %.12f %d %.9f %.9f %.9f %.15f %.15f %.7f %.7f %.7f\n",
               id, nominal, angles[1] * R2D, time2gpst(sent, NULL), eph->iode,
               sat[0], sat[1], sat[2], clock, eph->tgd[0], range, ion, water);
    }
    return feof(stdin) ? 0 : 3;
}

static int point_rows(void)
{
    int id, week, count;
    double tow;
    prcopt_t options = prcopt_default;
    options.mode = PMODE_SINGLE;
    options.navsys = SYS_GPS;
    options.sateph = EPHOPT_BRDC;
    options.ionoopt = IONOOPT_BRDC;
    options.tropopt = TROPOPT_SAAS;
    options.elmin = 5.0 * D2R;
    options.posopt[4] = 1;
    while (scanf("%d %d %lf %d", &id, &week, &tow, &count) == 4) {
        obsd_t samples[MAXOBS] = {{0}};
        sol_t result = {0};
        char detail[128] = {0};
        if (count < 1 || count > MAXOBS) return 4;
        for (int i = 0; i < count; ++i) {
            int prn;
            double range, strength;
            if (scanf("%d %lf %lf", &prn, &range, &strength) != 3) return 3;
            samples[i].sat = satno(SYS_GPS, prn);
            samples[i].time = gpst2time(week, tow);
            samples[i].P[0] = range;
            samples[i].code[0] = CODE_L1C;
            samples[i].SNR[0] = (unsigned short)lround(strength / SNR_UNIT);
        }
        if (pntpos(samples, count, &navigation, &options, &result, NULL, NULL, detail)) {
            printf("%d %.8f %.8f %.8f %.12f %d %d\n", id, result.rr[0],
                   result.rr[1], result.rr[2], result.dtr[0], result.ns, result.stat);
        } else {
            printf("%d unavailable %s\n", id, detail);
        }
    }
    return feof(stdin) ? 0 : 3;
}

int main(int argc, char **argv)
{
    if (argc != 3 || (strcmp(argv[1], "predict") && strcmp(argv[1], "point"))) {
        fputs("usage: gnss_clock_audit_rtk predict|point nav.rnx\n", stderr);
        return 2;
    }
    if (readrnx(argv[2], 1, "-SYS=G", NULL, &navigation, NULL) <= 0 || !navigation.n) {
        fputs("RTKLIB could not read GPS navigation data\n", stderr);
        return 1;
    }
    return strcmp(argv[1], "predict") == 0 ? predict_rows() : point_rows();
}
