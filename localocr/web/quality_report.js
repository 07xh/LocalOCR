'use strict';
/* Pure, offline quality-report math shared by Studio and Node regression tests.
 * Reports include only aggregates and opaque dataset IDs, never OCR transcripts.
 */
(function (root) {
  const LENGTH_BUCKETS = ['1-4', '5-12', '13+'];
  const numberField = (value, name) => {
    if (!Number.isSafeInteger(value) || value < 0) throw new Error('Invalid metric: ' + name);
    return value;
  };
  function emptyGroup() {
    return {regions: 0, exact_matches: 0, edit_errors: 0, reference_characters: 0};
  }
  function createAccumulator() {
    return {
      samples: 0, regions: 0, exact: 0, errors: 0, chars: 0,
      elapsed: 0, blanks: 0, engines: new Set(), examples: [],
      groups: Object.fromEntries(LENGTH_BUCKETS.map(name => [name, emptyGroup()])),
      available: null, fingerprint: null, nextOffset: 0, batches: 0,
      lastEvaluatedAt: null
    };
  }
  function includePage(state, page) {
    if (!page || typeof page !== 'object') throw new Error('Invalid OCR evaluation page');
    const offset = numberField(page.offset, 'offset');
    const nextOffset = numberField(page.next_offset, 'next_offset');
    const total = numberField(page.available_test_samples, 'available_test_samples');
    const sampleCount = numberField(page.evaluated_samples, 'evaluated_samples');
    const regions = numberField(page.evaluated_regions, 'evaluated_regions');
    const exact = numberField(page.exact_matches, 'exact_matches');
    const errors = numberField(page.edit_errors, 'edit_errors');
    const chars = numberField(page.reference_characters, 'reference_characters');
    const elapsed = numberField(page.inference_ms_total, 'inference_ms_total');
    const blanks = numberField(page.quality?.empty_predictions, 'empty_predictions');
    const fingerprint = page.dataset_fingerprint;
    if (typeof fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(fingerprint)) {
      throw new Error('Missing dataset revision fingerprint');
    }
    if (offset !== state.nextOffset || nextOffset !== offset + sampleCount ||
        nextOffset > total || sampleCount < 1 || regions < sampleCount ||
        exact > regions || blanks > regions || chars < regions ||
        page.has_more !== (nextOffset < total)) {
      throw new Error('Invalid or overlapping OCR evaluation page');
    }
    if (state.available !== null && (state.available !== total ||
        state.fingerprint !== fingerprint)) {
      throw new Error('Reviewed test dataset changed during evaluation');
    }
    if (!Array.isArray(page.actual_engines) || !page.actual_engines.length ||
        !Array.isArray(page.error_examples) ||
        !page.quality || !page.quality.by_reference_length) {
      throw new Error('Incomplete OCR quality metrics');
    }
    const groups = {};
    let groupRegions = 0, groupExact = 0, groupErrors = 0, groupChars = 0;
    for (const name of LENGTH_BUCKETS) {
      const source = page.quality.by_reference_length[name];
      if (!source) throw new Error('Missing OCR length group ' + name);
      const group = {
        regions: numberField(source.regions, name + '.regions'),
        exact_matches: numberField(source.exact_matches, name + '.exact_matches'),
        edit_errors: numberField(source.edit_errors, name + '.edit_errors'),
        reference_characters: numberField(source.reference_characters, name + '.chars')
      };
      if (group.exact_matches > group.regions ||
          (group.regions === 0 && (group.edit_errors || group.reference_characters))) {
        throw new Error('Invalid OCR length group ' + name);
      }
      groups[name] = group;
      groupRegions += group.regions;
      groupExact += group.exact_matches;
      groupErrors += group.edit_errors;
      groupChars += group.reference_characters;
    }
    if (groupRegions !== regions || groupExact !== exact ||
        groupErrors !== errors || groupChars !== chars) {
      throw new Error('OCR category subtotals disagree with page totals');
    }
    if (state.available === null) {
      state.available = total;
      state.fingerprint = fingerprint;
    }
    state.samples += sampleCount;
    state.regions += regions;
    state.exact += exact;
    state.errors += errors;
    state.chars += chars;
    state.elapsed += elapsed;
    state.blanks += blanks;
    state.nextOffset = nextOffset;
    state.batches++;
    state.lastEvaluatedAt = page.evaluated_at || null;
    for (const name of page.actual_engines) state.engines.add(String(name));
    for (const name of LENGTH_BUCKETS) {
      for (const metric of Object.keys(groups[name])) {
        state.groups[name][metric] += groups[name][metric];
      }
    }
    for (const entry of page.error_examples) {
      if (state.examples.length >= 10) break;
      // Deliberate allowlist prevents accidental inclusion of model/label text.
      if (typeof entry.sample_id === 'string' && /^[a-f0-9]{32}$/.test(entry.sample_id)) {
        state.examples.push({
          sample_id: entry.sample_id,
          region_index: numberField(entry.region_index, 'region_index'),
          edit_errors: numberField(entry.edit_errors, 'edit_errors'),
          reference_length: numberField(entry.reference_length, 'reference_length'),
          prediction_length: numberField(entry.prediction_length, 'prediction_length')
        });
      }
    }
    return state;
  }
  function finalize(state, options = {}) {
    const reason = options.reason || 'partial';
    const complete = reason === 'complete' && state.samples > 0 &&
      state.available === state.samples && state.nextOffset === state.available;
    if (reason === 'complete' && !complete) throw new Error('Cannot mark partial OCR evaluation complete');
    const rate = (numerator, denominator) => denominator ? Number((numerator / denominator).toFixed(6)) : null;
    const groups = Object.fromEntries(LENGTH_BUCKETS.map(name => {
      const g = state.groups[name];
      return [name, {
        ...g,
        exact_match_rate: rate(g.exact_matches, g.regions),
        cer: rate(g.edit_errors, g.reference_characters)
      }];
    }));
    return {
      format: 'localocr-reviewed-test-quality-v1',
      generated_at: new Date().toISOString(),
      requested_engine: options.engine || 'auto',
      actual_engines: [...state.engines].sort(),
      evaluation: {
        status: complete ? 'complete' : reason,
        complete,
        dataset_fingerprint: state.fingerprint,
        total_test_samples: state.available,
        evaluated_samples: state.samples,
        evaluated_regions: state.regions,
        batches: state.batches,
        last_evaluated_at: state.lastEvaluatedAt
      },
      metrics: {
        exact_matches: state.exact,
        exact_match_rate: rate(state.exact, state.regions),
        edit_errors: state.errors,
        reference_characters: state.chars,
        cer: rate(state.errors, state.chars),
        empty_predictions: state.blanks,
        inference_ms_total: state.elapsed,
        inference_ms_mean: rate(state.elapsed, state.regions),
        by_reference_length: groups
      },
      error_examples: state.examples.map(entry => ({...entry})),
      note: 'Local OCR recognition on reviewed test crops only; no source text, predictions, or images included.'
    };
  }
  const api = Object.freeze({createAccumulator, includePage, finalize, LENGTH_BUCKETS});
  root.LocalOCRQualityReport = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
