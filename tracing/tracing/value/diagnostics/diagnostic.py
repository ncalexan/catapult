# Copyright 2017 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import uuid

from py_utils import camel_case
from py_utils import discover
from tracing import tracing_project


class Diagnostic(object):
  _subtypes = None

  def __init__(self):
    self._guid = None

  @property
  def guid(self):
    if self._guid is None:
      self._guid = str(uuid.uuid4())
    return self._guid

  @guid.setter
  def guid(self, g):
    assert self._guid is None
    self._guid = g

  @property
  def has_guid(self):
    return self._guid is not None

  def AsDictOrReference(self):
    if self._guid:
      return self._guid
    return self.AsDict()

  def AsDict(self):
    dct = {'type': self.__class__.__name__}
    if self._guid:
      dct['guid'] = self._guid
    self._AsDictInto(dct)
    return dct

  def _AsDictInto(self, unused_dct):
    raise NotImplementedError

  @staticmethod
  def FromDict(dct):
    cls = Diagnostic.GetDiagnosticType(dct['type'])
    if not cls:
      raise ValueError('Unrecognized diagnostic type: ' + dct['type'])
    diagnostic = cls.FromDict(dct)
    if 'guid' in dct:
      diagnostic.guid = dct['guid']
    return diagnostic

  @staticmethod
  def GetDiagnosticType(typename):
    if not Diagnostic._subtypes:
      Diagnostic._subtypes = discover.DiscoverClasses(
          os.path.join(tracing_project.TracingProject.tracing_src_path,
                       'value'),
          tracing_project.TracingProject.tracing_root_path,
          Diagnostic, index_by_class_name=True)

    # TODO(eakuefner): Add camelcase mode to discover.DiscoverClasses.
    return Diagnostic._subtypes.get(camel_case.ToUnderscore(typename))

  def Inline(self):
    """Inlines a shared diagnostic.

    Any diagnostic that has a guid will be serialized as a reference, because it
    is assumed that diagnostics with guids are shared. This method removes the
    guid so that the diagnostic will be serialized by value.

    Inling is used for example in the dashboard, where certain types of shared
    diagnostics that vary on a per-upload basis are inlined for efficiency
    reasons.
    """
    self._guid = None

  def CanAddDiagnostic(self, unused_other_diagnostic, unused_name,
                       unused_parent_hist, unused_other_parent_hist):
    return False

  def AddDiagnostic(self, unused_other_diagnostic, unused_name,
                    unused_parent_hist, unused_other_parent_hist):
    raise Exception('Abstract virtual method: subclasses must override '
                    'this method if they override canAddDiagnostic')