"""
Annotated Matrix
"""
import sys
from collections import Mapping
from enum import Enum
import numpy as np
from numpy import ma
from numpy.lib.recfunctions import append_fields
from scipy import sparse as sp
from scipy.sparse.sputils import IndexMixin

class StorageType(Enum):
    Array = np.ndarray
    Masked = ma.MaskedArray
    Sparse = sp.spmatrix

    @classmethod
    def classes(cls):
        return tuple(c.value for c in cls.__members__.values())

SMP_NAMES = 'smp_names'
VAR_NAMES = 'var_names'

class BoundRecArr(np.recarray):
    """
    A np.recarray which can be constructed from a dict.
    Can be bound to AnnData to allow adding fields
    """
    def __new__(cls, source, nr_row, name_col, parent=None):
        if source is None:  # empty array
            cols = [np.arange(nr_row)]
            dtype = [(name_col, 'int64')]
        elif isinstance(source, np.recarray):
            cols = [source[n] for n in source.dtype.names]
            dtype = source.dtype
        else:
            if not isinstance(source, Mapping):
                raise ValueError(
                    'meta needs to be a recarray or dictlike, not {}'
                    .format(type(source)))
            # meta is dict-like
            names = list(source.keys())
            cols = [np.asarray(col) for col in source.values()]
            if name_col not in source:
                names.append(name_col)
                cols.append(np.arange(nr_row))
            dtype = list(zip(names, [str(c.dtype) for c in cols]))
        try:
            dtype = np.dtype(dtype)
        except TypeError:
            print(dtype, file=sys.stderr)
            raise

        arr = np.recarray.__new__(cls, (len(cols[0]),), dtype)
        arr._parent = parent
        arr._name_col = name_col

        for i, name in enumerate(dtype.names):
            arr[name] = np.array(cols[i])

        return arr

    @property
    def columns(self):
        return [c for c in self.dtype.names if not c == self._name_col]

    def __setitem__(self, key, value):
        if self._parent and key not in self.dtype.names:
            attr = 'smp' if self._name_col == SMP_NAMES else 'var'
            value = np.asarray(value)
            if len(value) > len(self):
                raise ValueError('New column has too many entries ({} > {})'
                                 .format(len(value), len(self)))
            source = append_fields(self, [key], [value],
                                   usemask=False, asrecarray=True)
            new = BoundRecArr(source, len(self), self._name_col, self._parent)
            setattr(self._parent, attr, new)
        else:
            super(BoundRecArr, self).__setitem__(key, value)

def _check_dimensions(data, smp, var):
    nr_smp, nr_var = data.shape
    if len(smp) != nr_smp:
        raise ValueError('Sample metadata needs to have the same amount of '
                         'rows as data has ({}), but has {} rows'
                         .format(nr_smp, smp.shape[0]))
    if len(var) != nr_var:
        raise ValueError('Feature metadata needs to have the same amount of '
                         'rows as data has columns ({}), but has {} rows'
                         .format(nr_var, var.shape[0]))

class AnnData(IndexMixin):
    def __init__(self, X, smp=None, var=None, vis=None, **meta):
        u"""
        Annotated Matrix

        Represents a sample × variable matrix (e.g. cell × gene) with the
        possibility to store an arbitrary number of annotations for both
        samples and variables.

        All named parameters will be stored as attributes. You can access
        additional metadata elements directly from the AnnData:

        >>> adata = AnnData(np.eye(3), k=1)
        >>> assert adata['k'] == 1

        Visualization metadata (`vis`) is a dict mapping `smp_meta` column
        names to colors. Possible values can be either a palette (a list of
        colors) or a dict/function mapping values from the corresponding
        metadata column to colors, e.g.:

        >>> from collections import OrderedDict
        >>> from matplotlib import cm
        >>> vis = {
        ...     'Col1': ['#ff3300', '#ffcc88'],
        ...     'Col2': {'V1': '#ff3300', 'V2': '#ffcc88'},  # no order!
        ...     'Col3': OrderedDict([('V1', '#ff3300'), ('V2', '#ffcc88')]),
        ...     'Col4': cm.magma,
        ... }

        Parameters
        ----------
        X : np.ndarray, np.ma.MaskedArray, sp.spmatrix
            A sample × variable matrix
        smp : np.recarray | dict
            A sample × ? record array containing sample names (`smp_names`)
            and other sample metadata columns. A passed dict will be
            converted to a record array.
        var : np.recarray | dict
            The same as `smp_meta`, only for variable metadata.
        vis : dict
            A dict containing visualization metadata.
        **meta : dict
            Unstructured metadata for the whole dataset.
        """

        # check data type of X
        for s_type in StorageType:
            if isinstance(X, s_type.value):
                self.storage_type = s_type
                break
        else:
            class_names = ', '.join(c.__name__ for c in StorageType.classes())
            raise ValueError(
                '`data` needs to be of one of the following types, not {}: [{}]'
                .format(type(X), class_names))

        if len(X.shape) == 1:
            X.shape = (X.shape[0], 1)
        if X.dtype.names is None and len(X.shape) != 2:
            raise ValueError('X needs to be 2-dimensional, not '
                             '{}D'.format(len(X.shape)))

        nr_smp, nr_var = X.shape

        self.X = X

        self.smp = BoundRecArr(smp, nr_smp, SMP_NAMES, self)
        self.var = BoundRecArr(var, nr_var, VAR_NAMES, self)

        _check_dimensions(X, self.smp, self.var)

        self.vis = vis or {}
        self._meta = meta

    @classmethod
    def from_ddata(cls, X=None, rownames=None, colnames=None, **meta):
        """
        Temporary helper to an AnnData from a “ddata” dict.

        Parameters
        ----------
        X : n×p data matrix
        rownames : n-length array of samples
        colnames : n-length array of variables
        """
        if X is None:
            raise ValueError('Missing data. Got instead {}'.format(meta.keys()))

        smp_meta = var_meta = None
        if rownames is not None:
            smp_meta = np.rec.fromarrays([np.asarray(rownames)], names=[SMP_NAMES])
        if colnames is not None:
            var_meta = np.rec.fromarrays([np.asarray(colnames)], names=[VAR_NAMES])

        return cls(X, smp_meta, var_meta, **meta)

    @property
    def smp_names(self):
        return self.smp[SMP_NAMES]

    @smp_names.setter
    def smp_names(self, keys):
        self.smp[SMP_NAMES] = keys

    @property
    def var_names(self):
        return self.var[VAR_NAMES]

    @var_names.setter
    def var_names(self, keys):
        self.var[VAR_NAMES] = keys

    def _unpack_index(self, index):
        smp, var = super(AnnData, self)._unpack_index(index)
        if isinstance(smp, int):
            smp = slice(smp, smp+1)
        if isinstance(var, int):
            var = slice(var, var+1)
        return smp, var

    def __delitem__(self, index):
        smp, var = self._unpack_index(index)
        del self.X[smp, var]
        if var == slice(None):
            del self.smp.iloc[smp, :]
        if smp == slice(None):
            del self.var.iloc[var, :]

    def __getitem__(self, index):
        if isinstance(index, str):
            return self._meta[index]

        smp, var = self._unpack_index(index)
        data = self.X[smp, var]
        smp_meta = self.smp[smp]
        var_meta = self.var[var]

        assert smp_meta.shape[0] == data.shape[0], (smp, smp_meta)
        assert var_meta.shape[0] == data.shape[1], (var, var_meta)
        return AnnData(data, smp_meta, var_meta, self.vis, **self._meta)

    def __setitem__(self, index, val):
        if isinstance(index, str):
            self._meta[index] = val
            return

        samp, feat = self._unpack_index(index)
        self.X[samp, feat] = val

    def __contains__(self, item):
        return item in self._meta

    def get(self, key, default=None):
        return self._meta.get(key, default)

    def __len__(self):
        return self.X.shape[0]

    def transpose(self):
        smp = np.rec.array(self.var)
        smp.dtype.names = [SMP_NAMES if n == VAR_NAMES else n
                           for n in smp.dtype.names]
        var = np.rec.array(self.smp)
        var.dtype.names = [VAR_NAMES if n == SMP_NAMES else n
                           for n in var.dtype.names]
        return AnnData(self.X.T, smp, var, self.vis, **self._meta)

    T = property(transpose)

def test_creation():
    AnnData(np.array([[1, 2], [3, 4]]))
    AnnData(ma.array([[1, 2], [3, 4]], mask=[0, 1, 1, 0]))
    AnnData(sp.eye(2))
    AnnData(
        np.array([[1, 2, 3], [4, 5, 6]]),
        dict(Smp=['A', 'B']),
        dict(Feat=['a', 'b', 'c']))

    from pytest import raises
    raises(ValueError, AnnData, np.array([1]))
    raises(ValueError, AnnData,
           np.array([[1, 2], [3, 4]]),
           dict(TooLong=[1, 2, 3, 4]))

def test_ddata():
    ddata = dict(
        X=np.array([[1, 2, 3], [4, 5, 6]]),
        rownames=['A', 'B'],
        colnames=['a', 'b', 'c'])
    AnnData.from_ddata(**ddata)

def test_names():
    adata = AnnData(
        np.array([[1, 2, 3], [4, 5, 6]]),
        dict(smp_names=['A', 'B']),
        dict(var_names=['a', 'b', 'c']))

    assert adata.smp_names.tolist() == 'A B'.split()
    assert adata.var_names.tolist() == 'a b c'.split()

def test_get_subset():
    mat = AnnData(np.array([[1, 2, 3], [4, 5, 6]]))

    assert mat[0, 0].X.tolist() == [[1]]
    assert mat[0, :].X.tolist() == [[1, 2, 3]]
    assert mat[:, 0].X.tolist() == [[1], [4]]
    assert mat[:, [0, 1]].X.tolist() == [[1, 2], [4, 5]]
    assert mat[:, 1:3].X.tolist() == [[2, 3], [5, 6]]

def test_get_subset_meta():
    mat = AnnData(np.array([[1, 2, 3], [4, 5, 6]]),
                  dict(Smp=['A', 'B']),
                  dict(Feat=['a', 'b', 'c']))

    assert mat[0, 0].smp['Smp'].tolist() == ['A']
    assert mat[0, 0].var['Feat'].tolist() == ['a']

def test_append_meta_col():
    mat = AnnData(np.array([[1, 2, 3], [4, 5, 6]]))

    mat.smp['new_col'] = [1, 2]

    from pytest import raises
    with raises(ValueError):
        mat.smp['new_col2'] = 'far too long'.split()
