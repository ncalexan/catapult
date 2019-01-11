# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import json
import os
import tempfile

from tracing.value import histogram_set
from tracing.value import merge_histograms
from tracing.value.diagnostics import generic_set
from tracing.value.diagnostics import reserved_infos


ALL_NAMES = list(reserved_infos.AllNames())


def _LoadHistogramSet(dicts):
  hs = histogram_set.HistogramSet()
  hs.ImportDicts(dicts)
  return hs


@contextlib.contextmanager
def TempFile():
  try:
    temp = tempfile.NamedTemporaryFile(delete=False)
    yield temp
  finally:
    os.unlink(temp.name)


def GetTIRLabelFromHistogram(hist):
  tags = hist.diagnostics.get(reserved_infos.STORY_TAGS.name) or []

  tags_to_use = [t.split(':') for t in tags if ':' in t]

  return '_'.join(v for _, v in sorted(tags_to_use))


def ComputeTestPath(hist):
  path = hist.name

  # If a Histogram represents a summary across multiple stories, then its
  # 'stories' diagnostic will contain the names of all of the stories.
  # If a Histogram is not a summary, then its 'stories' diagnostic will contain
  # the singular name of its story.
  is_summary = list(
      hist.diagnostics.get(reserved_infos.SUMMARY_KEYS.name, []))

  tir_label = GetTIRLabelFromHistogram(hist)
  if tir_label and (
      not is_summary or reserved_infos.STORY_TAGS.name in is_summary):
    path += '/' + tir_label

  is_ref = hist.diagnostics.get(reserved_infos.IS_REFERENCE_BUILD.name)
  if is_ref and len(is_ref) == 1:
    is_ref = is_ref.GetOnlyElement()

  story_name = hist.diagnostics.get(reserved_infos.STORIES.name)
  if story_name and len(story_name) == 1 and not is_summary:
    escaped_story_name = story_name.GetOnlyElement()
    path += '/' + escaped_story_name
    if is_ref:
      path += '_ref'
  elif is_ref:
    path += '/ref'

  return path


def _MergeHistogramSetByPath(hs):
  with TempFile() as temp:
    temp.write(json.dumps(hs.AsDicts()).encode('utf-8'))
    temp.close()

    return merge_histograms.MergeHistograms(temp.name, (
        reserved_infos.TEST_PATH.name,))


def _GetAndDeleteHadFailures(hs):
  had_failures = False
  for h in hs:
    had_failures_diag = h.diagnostics.get(reserved_infos.HAD_FAILURES.name)
    if had_failures_diag:
      del h.diagnostics[reserved_infos.HAD_FAILURES.name]
      had_failures = True
  return had_failures


def _MergeAndReplaceSharedDiagnostics(diagnostic_name, hs):
  merged = None
  for h in hs:
    d = h.diagnostics.get(diagnostic_name)
    if not d:
      continue

    if not merged:
      merged = d
    else:
      merged.AddDiagnostic(d)
      h.diagnostics[diagnostic_name] = merged


def AddReservedDiagnostics(histogram_dicts, names_to_values):
  # We need to generate summary statistics for anything that had a story, so
  # filter out every histogram with no stories, then merge. If you keep the
  # histograms with no story, you end up with duplicates.
  hs_with_stories = _LoadHistogramSet(histogram_dicts)
  hs_with_stories.FilterHistograms(
      lambda h: not h.diagnostics.get(reserved_infos.STORIES.name, []))

  hs_with_no_stories = _LoadHistogramSet(histogram_dicts)
  hs_with_no_stories.FilterHistograms(
      lambda h: h.diagnostics.get(reserved_infos.STORIES.name, []))

  # TODO(#3987): Refactor recipes to call merge_histograms separately.
  # This call combines all repetitions of a metric for a given story into a
  # single histogram.
  hs = histogram_set.HistogramSet()
  hs.ImportDicts(hs_with_stories.AsDicts())

  for h in hs:
    h.diagnostics[reserved_infos.TEST_PATH.name] = (
        generic_set.GenericSet([ComputeTestPath(h)]))

  _GetAndDeleteHadFailures(hs)
  dicts_across_repeats = _MergeHistogramSetByPath(hs)

  had_failures = _GetAndDeleteHadFailures(hs_with_stories)

  if not had_failures:
    # This call creates summary metrics across each tag set of stories.
    hs = histogram_set.HistogramSet()
    hs.ImportDicts(hs_with_stories.AsDicts())
    hs.FilterHistograms(lambda h: not GetTIRLabelFromHistogram(h))

    for h in hs:
      h.diagnostics[reserved_infos.SUMMARY_KEYS.name] = (
          generic_set.GenericSet(['name', 'storyTags']))
      h.diagnostics[reserved_infos.TEST_PATH.name] = (
          generic_set.GenericSet([ComputeTestPath(h)]))

    dicts_across_stories = _MergeHistogramSetByPath(hs)

    # This call creates summary metrics across the entire story set.
    hs = histogram_set.HistogramSet()
    hs.ImportDicts(hs_with_stories.AsDicts())

    for h in hs:
      h.diagnostics[reserved_infos.SUMMARY_KEYS.name] = (
          generic_set.GenericSet(['name']))
      h.diagnostics[reserved_infos.TEST_PATH.name] = (
          generic_set.GenericSet([ComputeTestPath(h)]))

    dicts_across_names = _MergeHistogramSetByPath(hs)
  else:
    dicts_across_stories = []
    dicts_across_names = []

  # Now load everything into one histogram set. First we load the summary
  # histograms, since we need to mark them with SUMMARY_KEYS.
  # After that we load the rest, and then apply all the diagnostics specified
  # on the command line. Finally, since we end up with a lot of diagnostics
  # that no histograms refer to, we make sure to prune those.
  histograms = histogram_set.HistogramSet()
  histograms.ImportDicts(dicts_across_names)
  histograms.ImportDicts(dicts_across_stories)
  histograms.ImportDicts(dicts_across_repeats)
  histograms.ImportDicts(hs_with_no_stories.AsDicts())

  # Merge tagmaps since we OBBS may produce several for shared runs
  _MergeAndReplaceSharedDiagnostics(
      reserved_infos.TAG_MAP.name, histograms)

  histograms.DeduplicateDiagnostics()
  for name, value in names_to_values.items():
    assert name in ALL_NAMES
    histograms.AddSharedDiagnosticToAllHistograms(
        name, generic_set.GenericSet([value]))
  histograms.RemoveOrphanedDiagnostics()

  return json.dumps(histograms.AsDicts())
