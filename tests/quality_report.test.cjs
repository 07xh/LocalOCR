'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {createAccumulator, includePage, finalize} =
  require('../localocr/web/quality_report.js');

const fingerprint = 'a'.repeat(64);
function emptyGroup() {
  return {regions: 0, exact_matches: 0, edit_errors: 0, reference_characters: 0};
}
function page({offset = 0, total = 2, textLength = 2, correct = true,
               fingerprintValue = fingerprint, engine = 'rapidocr'} = {}) {
  const band = textLength <= 4 ? '1-4' : textLength <= 12 ? '5-12' : '13+';
  const correctCount = correct ? 1 : 0;
  const errors = correct ? 0 : 3;
  const buckets = {'1-4': emptyGroup(), '5-12': emptyGroup(), '13+': emptyGroup()};
  buckets[band] = {regions: 1, exact_matches: correctCount,
                   edit_errors: errors, reference_characters: textLength};
  return {
    status: 'evaluated_local_engine', evaluated_at: '2026-11-23T00:00:00Z',
    available_test_samples: total, dataset_fingerprint: fingerprintValue,
    offset, next_offset: offset + 1, has_more: offset + 1 < total,
    evaluated_samples: 1, evaluated_regions: 1, exact_matches: correctCount,
    edit_errors: errors, reference_characters: textLength,
    inference_ms_total: offset ? 30 : 10,
    actual_engines: [engine],
    quality: {empty_predictions: correct ? 0 : 1, by_reference_length: buckets},
    error_examples: correct ? [] : [{
      sample_id: 'b'.repeat(32), region_index: 0, edit_errors: errors,
      reference_length: textLength, prediction_length: 0,
      reference_text: 'SECRET REFERENCE', predicted_text: 'SECRET PREDICTION'
    }]
  };
}
test('weighted total CER and exact matches, with privacy-safe JSON', () => {
  const agg = createAccumulator();
  includePage(agg, page({textLength: 2}));
  includePage(agg, page({offset: 1, textLength: 6, correct: false}));
  const report = finalize(agg, {reason: 'complete', engine: 'rapidocr'});
  assert.equal(report.evaluation.complete, true);
  assert.equal(report.evaluation.evaluated_samples, 2);
  assert.equal(report.evaluation.batches, 2);
  assert.equal(report.metrics.cer, 0.375); // 3 edits / 8 chars, not mean of page CERs
  assert.equal(report.metrics.exact_match_rate, 0.5);
  assert.equal(report.metrics.inference_ms_mean, 20);
  assert.equal(report.metrics.empty_predictions, 1);
  assert.equal(report.metrics.by_reference_length['1-4'].exact_match_rate, 1);
  assert.equal(report.metrics.by_reference_length['5-12'].cer, 0.5);
  assert.equal(report.metrics.by_reference_length['13+'].cer, null);
  assert.equal(report.evaluation.dataset_fingerprint, fingerprint);
  assert.deepEqual(report.actual_engines, ['rapidocr']);
  const serialized = JSON.stringify(report);
  assert.ok(!serialized.includes('SECRET REFERENCE'));
  assert.ok(!serialized.includes('SECRET PREDICTION'));
  assert.equal(report.error_examples[0].sample_id, 'b'.repeat(32));
});

test('cancel and hard limits must never be mislabeled complete', () => {
  const agg = createAccumulator();
  includePage(agg, page({total: 7}));
  const partial = finalize(agg, {reason: 'cancelled'});
  assert.equal(partial.evaluation.complete, false);
  assert.equal(partial.evaluation.status, 'cancelled');
  assert.equal(partial.evaluation.total_test_samples, 7);
  assert.throws(() => finalize(agg, {reason: 'complete'}), /partial/);
  assert.equal(finalize(createAccumulator(), {reason: 'failed'}).metrics.cer, null);
});

test('reject duplicate, skipped, modified or invalid metric pages atomically', () => {
  const agg = createAccumulator();
  includePage(agg, page());
  const prior = agg.samples;
  assert.throws(() => includePage(agg, page({offset: 0})), /overlapping/);
  assert.throws(() => includePage(agg, page({offset: 1, fingerprintValue: 'f'.repeat(64)})), /changed/);
  const invalid = page({offset: 1});
  invalid.quality.by_reference_length['1-4'].regions = 10;
  assert.throws(() => includePage(agg, invalid), /subtotals/);
  assert.equal(agg.samples, prior);
  includePage(agg, page({offset: 1, correct: false}));
  assert.equal(agg.samples, 2);
});

test('reject forged transcript-bearing error examples without leaking them', () => {
  const agg = createAccumulator();
  const bad = page({correct: false, total: 1});
  bad.error_examples[0].sample_id = '../../private';
  includePage(agg, bad);
  assert.deepEqual(finalize(agg, {reason: 'complete'}).error_examples, []);
});
