/**
 * Node.js unit tests for static/workout-logic.js
 * Run with: node --test tests/workout-logic.test.mjs
 * Requires Node.js >= 18 (built-in test runner).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const {
    PRESET_RULES,
    getRules,
    validateAndClamp,
    lbsToKg,
    kgToLbs,
    parseImportedSets,
    buildExportJSON,
    resolveAlreadyExpanded,
    deriveCardioStats,
} = require(path.join(__dirname, '..', 'static', 'workout-logic.js'));

// ---------------------------------------------------------------------------
// PRESET_RULES sanity checks
// ---------------------------------------------------------------------------
test('PRESET_RULES has four entries', () => {
    const keys = Object.keys(PRESET_RULES);
    assert.deepEqual(keys.sort(), ['-1', '1', '3', '5'].sort());
});

test('Gain Muscle RM range is 9-13', () => {
    assert.equal(PRESET_RULES['1'].minW, 9);
    assert.equal(PRESET_RULES['1'].maxW, 13);
});

test('Stamina RM range is 15-20', () => {
    assert.equal(PRESET_RULES['3'].minW, 15);
    assert.equal(PRESET_RULES['3'].maxW, 20);
});

test('Strength RM range is 4-9', () => {
    assert.equal(PRESET_RULES['5'].minW, 4);
    assert.equal(PRESET_RULES['5'].maxW, 9);
});

// ---------------------------------------------------------------------------
// getRules — metric
// ---------------------------------------------------------------------------
test('getRules metric dual-handle (separate cables): minW=3.5, maxW=100, step=0.5', () => {
    const ex = { selectedPresetId: -1, isUnilateral: false, isBarbell: false };
    const r = getRules(ex, 0);
    assert.equal(r.minW, 3.5);
    assert.equal(r.maxW, 100);
    assert.equal(r.step, 0.5);
    assert.equal(r.label, 'KG');
});

test('getRules metric barbell (both cables joined): minW=7, maxW=100', () => {
    const ex = { selectedPresetId: -1, isUnilateral: false, isBarbell: true };
    const r = getRules(ex, 0);
    assert.equal(r.minW, 7);
    assert.equal(r.maxW, 100);
});

test('getRules metric unilateral: minW=3.5, maxW=50', () => {
    const ex = { selectedPresetId: -1, isUnilateral: true, isBarbell: false };
    const r = getRules(ex, 0);
    assert.equal(r.minW, 3.5);
    assert.equal(r.maxW, 50);
});

// ---------------------------------------------------------------------------
// getRules — imperial
// ---------------------------------------------------------------------------
test('getRules imperial bilateral: minW=15, maxW=220, label=LBS', () => {
    const ex = { selectedPresetId: -1, isUnilateral: false };
    const r = getRules(ex, 1);
    assert.equal(r.minW, 15);
    assert.equal(r.maxW, 220);
    assert.equal(r.label, 'LBS');
});

test('getRules imperial unilateral: minW=8, maxW=110', () => {
    const ex = { selectedPresetId: -1, isUnilateral: true };
    const r = getRules(ex, 1);
    assert.equal(r.minW, 8);
    assert.equal(r.maxW, 110);
});

// ---------------------------------------------------------------------------
// getRules — RM presets (should not be affected by userUnit)
// ---------------------------------------------------------------------------
test('getRules Gain Muscle preset returns RM rules regardless of unit', () => {
    const ex = { selectedPresetId: 1, isUnilateral: false };
    const rMetric = getRules(ex, 0);
    const rImperial = getRules(ex, 1);
    assert.equal(rMetric.minW, 9);
    assert.equal(rImperial.minW, 9);
    assert.equal(rMetric.label, 'RM');
});

// ---------------------------------------------------------------------------
// validateAndClamp
// ---------------------------------------------------------------------------
test('validateAndClamp: value below min is raised to min', () => {
    assert.equal(validateAndClamp(3.0, 3.5, 100, 0.5), 3.5);
});

test('validateAndClamp: value above max is lowered to max', () => {
    assert.equal(validateAndClamp(110, 3.5, 100, 0.5), 100);
});

test('validateAndClamp: value snapped to nearest 0.5 step', () => {
    assert.equal(validateAndClamp(5.3, 3.5, 100, 0.5), 5.5);
    assert.equal(validateAndClamp(5.1, 3.5, 100, 0.5), 5.0);
    assert.equal(validateAndClamp(4.75, 3.5, 100, 0.5), 5.0);
});

test('validateAndClamp: NaN is replaced with min', () => {
    assert.equal(validateAndClamp(NaN, 3.5, 100, 0.5), 3.5);
});

test('validateAndClamp: integer step works normally', () => {
    assert.equal(validateAndClamp(8, 9, 13, 1), 9);   // below min → min
    assert.equal(validateAndClamp(13, 9, 13, 1), 13); // at max → max
    assert.equal(validateAndClamp(11, 9, 13, 1), 11); // in range → unchanged
});

// ---------------------------------------------------------------------------
// lbsToKg
// ---------------------------------------------------------------------------
test('lbsToKg: 100 lbs → 45.5 kg', () => {
    assert.equal(lbsToKg(100), 45.5);
});

test('lbsToKg: 50 lbs → 22.5 kg', () => {
    assert.equal(lbsToKg(50), 22.5);
});

test('lbsToKg: result is multiple of 0.5', () => {
    for (const lbs of [10, 25, 55, 80, 110, 200]) {
        const kg = lbsToKg(lbs);
        assert.equal(kg % 0.5, 0, `lbsToKg(${lbs})=${kg} is not multiple of 0.5`);
    }
});

// ---------------------------------------------------------------------------
// kgToLbs
// ---------------------------------------------------------------------------
test('kgToLbs: 45.5 kg → 100 lbs', () => {
    assert.equal(kgToLbs(45.5), 100);
});

test('kgToLbs: 22.5 kg → 50 lbs', () => {
    assert.equal(kgToLbs(22.5), 50);
});

test('kgToLbs: returns integer', () => {
    assert.equal(Number.isInteger(kgToLbs(20)), true);
    assert.equal(Number.isInteger(kgToLbs(35.5)), true);
});

// ---------------------------------------------------------------------------
// round-trip: lbs → kg → lbs
// ---------------------------------------------------------------------------
test('LBS round-trip within 1 lb for typical values', () => {
    for (const lbs of [10, 25, 50, 55, 100, 110, 150, 200, 220]) {
        const kg = lbsToKg(lbs);
        const lbsBack = kgToLbs(kg);
        assert.ok(
            Math.abs(lbsBack - lbs) <= 1,
            `Round-trip fail: ${lbs} lbs → ${kg} kg → ${lbsBack} lbs (diff > 1)`
        );
    }
});

// ---------------------------------------------------------------------------
// parseImportedSets
// ---------------------------------------------------------------------------
test('parseImportedSets: bilateral — sets unchanged', () => {
    const sets = [{ reps: 10, weight: 20 }, { reps: 8, weight: 25 }];
    const result = parseImportedSets(sets, false, false);
    assert.equal(result.length, 2);
});

test('parseImportedSets: unilateral not expanded — 3 sets become 6', () => {
    const sets = [
        { reps: 10, weight: 6 },
        { reps: 10, weight: 6 },
        { reps: 8, weight: 7 },
    ];
    const result = parseImportedSets(sets, true, false);
    assert.equal(result.length, 6);
});

test('parseImportedSets: unilateral already expanded — 6 sets stay 6 (no doubling)', () => {
    const sets = [
        { reps: 10, weight: 6 }, { reps: 10, weight: 6 }, // L1, R1
        { reps: 10, weight: 6 }, { reps: 10, weight: 6 }, // L2, R2
        { reps: 8,  weight: 7 }, { reps: 8,  weight: 7 }, // L3, R3
    ];
    const result = parseImportedSets(sets, true, true);
    assert.equal(result.length, 6);
});

test('parseImportedSets: returns copies, not original references', () => {
    const sets = [{ reps: 10, weight: 20 }];
    const result = parseImportedSets(sets, false, false);
    result[0].reps = 99;
    assert.equal(sets[0].reps, 10); // original unchanged
});

// ---------------------------------------------------------------------------
// buildExportJSON
// ---------------------------------------------------------------------------
test('buildExportJSON: includes preset field', () => {
    const workoutData = [{
        groupId: 1,
        title: 'Bench Press',
        selectedPresetId: 1,
        isUnilateral: false,
        sets: [{ reps: 10, weight: 12, mode: 1, rest: 60 }]
    }];
    const result = buildExportJSON(workoutData, 'My Workout');
    assert.equal(result.exercises[0].preset, 1);
});

test('buildExportJSON: unilateral exercise has isUnilateralExpanded=true', () => {
    const workoutData = [{
        groupId: 2,
        title: 'Single Arm Row',
        selectedPresetId: -1,
        isUnilateral: true,
        sets: [
            { reps: 10, weight: 6, mode: 1, rest: 45 },
            { reps: 10, weight: 6, mode: 1, rest: 45 },
        ]
    }];
    const result = buildExportJSON(workoutData, 'Test');
    assert.equal(result.exercises[0].isUnilateralExpanded, true);
});

test('buildExportJSON: bilateral exercise has isUnilateralExpanded=false', () => {
    const workoutData = [{
        groupId: 3,
        title: 'Squat',
        selectedPresetId: -1,
        isUnilateral: false,
        sets: [{ reps: 10, weight: 20, mode: 1, rest: 60 }]
    }];
    const result = buildExportJSON(workoutData, 'Test');
    assert.equal(result.exercises[0].isUnilateralExpanded, false);
});

test('buildExportJSON: name is used', () => {
    const result = buildExportJSON([], 'Leg Day');
    assert.equal(result.name, 'Leg Day');
});

test('buildExportJSON: fallback name when empty', () => {
    const result = buildExportJSON([], '');
    assert.equal(result.name, 'Custom Workout');
});

// ---------------------------------------------------------------------------
// resolveAlreadyExpanded — the unilateral refine-round-trip guard
// ---------------------------------------------------------------------------
test('resolveAlreadyExpanded: model flag true -> expanded', () => {
    assert.equal(resolveAlreadyExpanded(true, 123, undefined), true);
});

test('resolveAlreadyExpanded: no flag, no hint -> not expanded (generation doubles)', () => {
    assert.equal(resolveAlreadyExpanded(false, 123, undefined), false);
});

test('resolveAlreadyExpanded: no flag but id in expandedIds -> expanded (refine echo, flag dropped)', () => {
    const ids = new Set([123, 456]);
    assert.equal(resolveAlreadyExpanded(undefined, 123, ids), true);
});

test('resolveAlreadyExpanded: no flag, id NOT in expandedIds -> not expanded (freshly swapped-in)', () => {
    const ids = new Set([456]);
    assert.equal(resolveAlreadyExpanded(false, 123, ids), false);
});

test('resolveAlreadyExpanded: coerces string groupId against numeric id set', () => {
    const ids = new Set([437972850049025]);
    assert.equal(resolveAlreadyExpanded(false, '437972850049025', ids), true);
});

// ---------------------------------------------------------------------------
// deriveCardioStats — mirrors cardio_stats.py (oracle trainingId 2023440)
// ---------------------------------------------------------------------------
const CARDIO_ORACLE = { trainingTime: 530, calorie: 161, totalEnergy: 29580.29,
                        totalDistance: 892.71, completionRate: 29.0, rpe: 6 };

test('deriveCardioStats: oracle session matches Python twin', () => {
    const r = deriveCardioStats(CARDIO_ORACLE);
    assert.equal(r.durationSec, 530);
    assert.ok(Math.abs(r.distanceM - 892.71) < 0.01);
    assert.ok(Math.abs(r.pace500 - 296.9) < 0.2, `pace500=${r.pace500}`);
    assert.ok(Math.abs(r.speedMs - 1.68) < 0.02, `speedMs=${r.speedMs}`);
    assert.ok(Math.abs(r.calPerMin - 18.2) < 0.2, `calPerMin=${r.calPerMin}`);
    assert.ok(Math.abs(r.energyKJ - 29.6) < 0.1, `energyKJ=${r.energyKJ}`);
    assert.ok(Math.abs(r.avgWatts - 56) < 1, `avgWatts=${r.avgWatts}`);
    assert.equal(r.completion, 29);
    assert.equal(r.rpe, 6);
});

test('deriveCardioStats: zero distance nulls pace and speed', () => {
    const r = deriveCardioStats({ trainingTime: 300, totalDistance: 0, calorie: 50 });
    assert.equal(r.pace500, null);
    assert.equal(r.speedMs, null);
    assert.ok(Math.abs(r.calPerMin - 10.0) < 0.1);
});

test('deriveCardioStats: missing fields are null, never NaN', () => {
    const r = deriveCardioStats({});
    for (const k of ['pace500', 'speedMs', 'calPerMin', 'avgWatts', 'distanceM', 'rpe']) {
        assert.equal(r[k], null, `${k} should be null`);
    }
});
