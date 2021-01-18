# coding: utf-8
"""Module for a seismic (or whatever) cube."""

import os.path
import tempfile

import numbers

import numpy as np

import xtgeo
from xtgeo.common import XTGeoDialog
from xtgeo.common import XTGDescription
import xtgeo.common.sys as xtgeosys

from xtgeo.cube import _cube_import
from xtgeo.cube import _cube_export
from xtgeo.cube import _cube_utils
from xtgeo.cube import _cube_roxapi


xtg = XTGeoDialog()
logger = xtg.functionlogger(__name__)

# Attributes and datamodel:
# _xori         : Origin in Easting coordinate
# _yori         : Origin in Northing coordinate
# _zori         : Origin in Depth coordinate, where depth is positive down
# _ncol         : Number of columns
# _nrow         : Number of columns
# _nlay         : Number of layers, starting from top
# _rotation     : Cube rotation, X axis is applied and "school-wise" rotation,
#                 anti-clock in degrees
# _values       : Numpy array with shape (ncol, nrow, nlay), C order, np.float32
# _filesrc      : String: Source file if any
# _yflip        : Normally 1; if -1 Y axis is flipped --> from left-handed (1) to
#                 right handed (-1). Right handed cubes are common.
# _ilines       : 1D numpy array with ncol elements, aka INLINES array
# _xlines       : 1D numpy array with nrow elements, aka XLINES array
# _traceidcodes : 2D array with trace ID codes
# _segyfile     : Name of SEGY file (not sure what the point of this is, TODO check)
# _undef        : Undef value, defaulted to xtgeo.UNDEF
#
# See also Cube section in documentation: docs/datamodel.rst
# ======================================================================================


def cube_from_file(mfile, fformat="guess"):
    """This makes an instance of a Cube directly from file import.

    Args:
        mfile (str): Name of file
        fformat (str): See :meth:`Cube.from_file`

    Example::

        import xtgeo
        mycube = xtgeo.cube_from_file('some_cube.segy')
    """
    obj = Cube()

    obj.from_file(mfile, fformat=fformat)

    return obj


def cube_from_roxar(project, name, folder=None):
    """This makes an instance of a Cube directly from roxar input.

    The folder is a string on form "a" or "a/b" if subfolders are present

    Example::

        import xtgeo
        mycube = xtgeo.cube_from_roxar(project, "DepthCube")

    """
    obj = Cube()

    obj.from_roxar(project, name, folder=folder)

    return obj


class Cube:  # pylint: disable=too-many-public-methods
    """Class for a (seismic) cube in the XTGeo framework.

    The values are stored as a 3D numpy array (4 bytes; float32 is default),
    with internal C ordering (nlay fastest).

    The cube object instance can be initialized by either a spesification, or via
    a file import. The import is most common, and usually SEGY, but also other
    formats are available (or will be).

    Examples::

        import xtgeo

        # a user defined cube:
        mycube = xtgeo.Cube(xori=100.0, yori=200.0, zori=150.0, ncol=40, nrow=30,
                            nlay=10, rotation=30, values=0)

        # or from a file
        mycube = xtgeo.Cube("somefile.segy", fformat="segy")

    """

    def __init__(
        self,
        *args,
        xori=0.0,
        yori=0.0,
        zori=0.0,
        ncol=5,
        nrow=3,
        nlay=2,
        xinc=25.0,
        yinc=25.0,
        zinc=2.0,
        yflip=1,
        values=0.0,
        rotation=0.0,
        **kwargs,
    ):
        """Initiate a Cube instance."""
        self._values = None

        self._filesrc = None
        self._xori = xori
        self._yori = yori
        self._zori = zori
        self._ncol = ncol
        self._nrow = nrow
        self._nlay = nlay
        self._xinc = xinc
        self._yinc = yinc
        self._zinc = zinc
        self._yflip = yflip
        self._zflip = 1  # currently not in use
        self._rotation = rotation
        self.values = values  # "values" is intentional over "_values"; cf. values()
        self._ilines = np.array(range(1, self._ncol + 1), dtype=np.int32)
        self._xlines = np.array(range(1, self._nrow + 1), dtype=np.int32)
        self._traceidcodes = np.ones((self._ncol, self._nrow), dtype=np.int32)
        self._segyfile = None
        self._metadata = xtgeo.MetaDataRegularCube()
        self._undef = xtgeo.UNDEF
        self.undef = xtgeo.UNDEF

        if len(args) >= 1:
            fformat = kwargs.get("fformat", "guess")
            self.from_file(args[0], fformat=fformat)

    def __repr__(self):
        """The __repr__ method."""
        avg = self.values.mean()
        dsc = (
            "{0.__class__} (ncol={0.ncol!r}, "
            "nrow={0.nrow!r}, nlay={0.nlay!r}, "
            "original file: {0._filesrc}), "
            "average {1}, ID=<{2}>".format(self, avg, id(self))
        )
        return dsc

    def __str__(self):
        """The __str__ method for pretty print."""
        return self.describe(flush=False)

    @property
    def metadata(self):
        """Return metadata object instance of type MetaDataRegularSurface."""
        return self._metadata

    @metadata.setter
    def metadata(self, obj):
        # The current metadata object can be replaced. This is a bit dangerous so
        # further check must be done to validate. TODO.
        if not isinstance(obj, xtgeo.MetaDataRegularCube):
            raise ValueError("Input obj not an instance of MetaDataRegularCube")

        self._metadata = obj  # checking is currently missing! TODO

    @property
    def ncol(self):
        """The NCOL (NX or I dir) number (read-only)."""
        return self._ncol

    @property
    def nrow(self):
        """The NROW (NY or J dir) number (read-only)."""
        return self._nrow

    @property
    def nlay(self):
        """The NLAY (or NZ or K dir) number (read-only)."""
        return self._nlay

    @property
    def dimensions(self):
        """3-tuple: The cube dimensions as a tuple of 3 integers (read only)."""
        return (self._ncol, self._nrow, self._nlay)

    @property
    def xori(self):
        """The XORI (origin corner) coordinate."""
        return self._xori

    @xori.setter
    def xori(self, val):
        logger.warning("Changing xori is risky!")
        self._xori = val

    @property
    def yori(self):
        """The YORI (origin corner) coordinate."""
        return self._yori

    @yori.setter
    def yori(self, val):
        logger.warning("Changing yori is risky!")
        self._yori = val

    @property
    def zori(self):
        """The ZORI (origin corner) coordinate."""
        return self._zori

    @zori.setter
    def zori(self, val):
        logger.warning("Changing zori is risky!")
        self._zori = val

    @property
    def xinc(self):
        """The XINC (increment X) as property."""
        return self._xinc

    @xinc.setter
    def xinc(self, val):
        logger.warning("Changing xinc is risky!")
        self._xinc = val

    @property
    def yinc(self):
        """The YINC (increment Y)."""
        return self._yinc

    @yinc.setter
    def yinc(self, val):
        logger.warning("Changing yinc is risky!")
        self._yinc = val

    @property
    def zinc(self):
        """The ZINC (increment Z)."""
        return self._zinc

    @zinc.setter
    def zinc(self, val):
        logger.warning("Changing zinc is risky!")
        self._zinc = val

    @property
    def rotation(self):
        """The rotation, anticlock from X axis in degrees."""
        return self._rotation

    @rotation.setter
    def rotation(self, val):
        logger.warning("Changing rotation is risky!")
        self._rotation = val

    @property
    def ilines(self):
        """The inlines numbering vector."""
        return self._ilines

    @ilines.setter
    def ilines(self, values):
        self._ilines = values

    @property
    def xlines(self):
        """The xlines numbering vector."""
        return self._xlines

    @xlines.setter
    def xlines(self, values):
        self._xlines = values

    @property
    def zslices(self):
        """Return the time/depth slices as an int array (read only)."""
        # This is a derived property
        zslices = range(
            int(self.zori), int(self.zori + self.nlay * self.zinc), int(self.zinc)
        )
        zslices = np.array(zslices)
        return zslices

    @property
    def traceidcodes(self):
        """The trace identifaction codes array (ncol, nrow)."""
        return self._traceidcodes

    @traceidcodes.setter
    def traceidcodes(self, values):
        self._traceidcodes = values.reshape(self.ncol, self.nrow)

    @property
    def yflip(self):
        """The YFLIP indicator, 1 is normal, -1 means Y flipped.

        YFLIP = 1 means a LEFT HANDED coordinate system with Z axis
        positive down, while inline (col) follow East (X) and xline (rows)
        follows North (Y), when rotation is zero.
        """
        return self._yflip

    @property
    def zflip(self):
        """The ZFLIP indicator, 1 is normal, -1 means Z flipped.

        ZFLIP = 1 and YFLIP = 1 means a LEFT HANDED coordinate system with Z axis
        positive down, while inline (col) follow East (X) and xline (rows)
        follows North (Y), when rotation is zero.
        """
        return self._zflip

    @property
    def segyfile(self):
        """The input segy file name (str), if any (or None) (read-only)."""
        return self._segyfile

    @property
    def filesrc(self):
        """The input file name (str), if any (or None) (read-only)."""
        return self._filesrc

    @filesrc.setter
    def filesrc(self, name):
        self._filesrc = name

    @property
    def values(self):
        """The values, as a 3D numpy (ncol, nrow, nlay), 4 byte float."""
        return self._values

    @values.setter
    def values(self, values):
        self._ensure_correct_values(values)

    # =========================================================================
    # Describe
    # =========================================================================

    def generate_hash(self, hashmethod="md5"):
        """Return a unique hash ID for current instance.

        See :meth:`~xtgeo.common.sys.generic_hash()` for documentation.

        .. versionadded:: 2.14
        """
        required = (
            "ncol",
            "nrow",
            "nlay",
            "xori",
            "yori",
            "zori",
            "xinc",
            "yinc",
            "zinc",
            "yflip",
            "zflip",
            "rotation",
            "values",
            "ilines",
            "xlines",
            "traceidcodes",
        )

        gid = ""
        for req in required:
            gid += f"{getattr(self, '_' + req)}"

        return xtgeosys.generic_hash(gid, hashmethod=hashmethod)

    def describe(self, flush=True):
        """Describe an instance by printing to stdout or return.

        Args:
            flush (bool): If True, description is printed to stdout.
        """
        dsc = XTGDescription()
        dsc.title("Description of Cube instance")
        dsc.txt("Object ID", id(self))
        dsc.txt("File source", self._filesrc)
        dsc.txt("Shape: NCOL, NROW, NLAY", self.ncol, self.nrow, self.nlay)
        dsc.txt("Origins XORI, YORI, ZORI", self.xori, self.yori, self.zori)
        dsc.txt("Increments XINC YINC ZINC", self.xinc, self.yinc, self.zinc)
        dsc.txt("Rotation (anti-clock from X)", self.rotation)
        dsc.txt("YFLIP flag", self.yflip)
        np.set_printoptions(threshold=16)
        dsc.txt("Inlines vector", self._ilines)
        dsc.txt("Xlines vector", self._xlines)
        dsc.txt("Time or depth slices vector", self.zslices)
        dsc.txt("Values", self._values.reshape(-1), self._values.dtype)
        np.set_printoptions(threshold=1000)
        dsc.txt(
            "Values, mean, stdev, minimum, maximum",
            self.values.mean(),
            self.values.std(),
            self.values.min(),
            self.values.max(),
        )
        dsc.txt("Trace ID codes", self._traceidcodes.reshape(-1))
        msize = float(self.values.size * 4) / (1024 * 1024 * 1024)
        dsc.txt("Minimum memory usage of array (GB)", msize)

        if flush:
            dsc.flush()
            return None

        return dsc.astext()

    # ==================================================================================
    # Copy, swapping, cropping, thinning...
    # ==================================================================================

    def copy(self):
        """Deep copy of a Cube() object to another instance.

        >>> mycube2 = mycube.copy()

        """
        xcube = Cube(
            ncol=self.ncol,
            nrow=self.nrow,
            nlay=self.nlay,
            xinc=self.xinc,
            yinc=self.yinc,
            zinc=self.zinc,
            xori=self.xori,
            yori=self.yori,
            zori=self.zori,
            yflip=self.yflip,
            segyfile=self.segyfile,
            rotation=self.rotation,
            values=self.values.copy(),
        )

        xcube.filesrc = self._filesrc

        xcube.ilines = self._ilines.copy()
        xcube.xlines = self._xlines.copy()
        xcube.traceidcodes = self._traceidcodes.copy()
        xcube.metadata.required = xcube

        return xcube

    def swapaxes(self, _algorithm=1):
        """Swap the axes inline vs xline, keep origin."""
        _cube_utils.swapaxes(self, _algorithm=_algorithm)

    def resample(self, incube, sampling="nearest", outside_value=None):
        """Resample a Cube object into this instance.

        Args:
            incube (Cube): A XTGeo Cube instance
            sampling (str): Sampling algorithm: 'nearest' for nearest node
                of 'trilinear' for trilinear interpoltion (more correct but
                slower)
            outside_value (None or float). If None, keep original, otherwise
                use this value

        Raises:
            ValueError: If cubes do not overlap

        Example:

            >>> mycube1 = Cube('mysegyfile.segy')
            >>> mycube2 = Cube(xori=461500, yori=5926800, zori=1550,
                   xinc=40, yinc=40, zinc=5, ncol=200, nrow=100,
                   nlay=100, rotation=mycube1.rotation)
            >>> mycube2.resample(mycube1)

        """
        _cube_utils.resample(
            self, incube, sampling=sampling, outside_value=outside_value
        )

    def do_thinning(self, icol, jrow, klay):
        """Thinning the cube by removing every N column, row and/or layer.

        Args:
            icol (int): Thinning factor for columns (usually inlines)
            jrow (int): Thinning factor for rows (usually xlines)
            klay (int): Thinning factor for layers

        Raises:
            ValueError: If icol, jrow or klay are out of reasonable range

        Example:

            >>> mycube1 = Cube('mysegyfile.segy')
            >>> mycube1.do_thinning(2, 2, 1)  # keep every second column, row
            >>> mycube1.to_file('mysegy_smaller.segy')

        """
        _cube_utils.thinning(self, icol, jrow, klay)

    def do_cropping(self, icols, jrows, klays, mode="edges"):
        """Cropping the cube by removing rows, columns, layers.

        Note that input boundary checking is currently lacking, and this
        is a currently a user responsibility!

        The 'mode' is used to determine to different 'approaches' on
        cropping. Examples for icols and mode 'edges':
        Here the tuple (N, M) will cut N first rows and M last rows.

        However, if mode is 'inclusive' then, it defines the range
        of rows to be included, and the numbering now shall be the
        INLINE, XLINE and DEPTH/TIME mode.

        Args:
            icols (int tuple): Cropping front, end of rows, or inclusive range
            jrows (int tuple): Cropping front, end of columns, or
                inclusive range
            klays (int tuple ): Cropping top, base layers, or inclusive range.
            mode (str): 'Default is 'edges'; alternative is 'inclusive'

        Example:
            Crop 10 columns from front, 2 from back, then 20 rows in front,
            40 in back, then no cropping of layers::

            >>> mycube1 = Cube('mysegyfile.segy')
            >>> mycube2 = mycube1.copy()
            >>> mycube1.do_cropping((10, 2), (20, 40), (0, 0))
            >>> mycube1.to_file('mysegy_smaller.segy')

            In stead, do cropping as 'inclusive' where inlines, xlines, slices
            arrays are known::

            >>> mycube2.do_cropping((112, 327), (1120, 1140), (1500, 2000))

        """
        useicols = icols
        usejrows = jrows
        useklays = klays

        if mode == "inclusive":
            # transfer to 'numbers to row/col/lay to remove' in front end ...
            useicols = (
                icols[0] - self._ilines[0],
                self._ilines[self._ncol - 1] - icols[1],
            )
            usejrows = (
                jrows[0] - self._xlines[0],
                self._xlines[self._nrow - 1] - jrows[1],
            )
            ntop = int((klays[0] - self.zori) / self.zinc)
            nbot = int((self.zori + self.nlay * self.zinc - klays[1] - 1) / (self.zinc))
            useklays = (ntop, nbot)

        logger.info(
            "Cropping at all cube sides: %s %s %s", useicols, usejrows, useklays
        )
        _cube_utils.cropping(self, useicols, usejrows, useklays)

    def values_dead_traces(self, newvalue):
        """Set values for traces flagged as dead.

        Dead traces have traceidcodes 2 and corresponding values in the cube
        will here receive a constant value to mimic "undefined".

        Args:
            newvalue (float): Set cube values to newvalues where traceid is 2.

        Return:
            oldvalue (float): The estimated simple 'average' of old value will
                be returned as (max + min)/2. If no dead traces, return None.
        """
        logger.info("Set values for dead traces, if any")

        if 2 in self._traceidcodes:
            minval = self._values[self._traceidcodes == 2].min()
            maxval = self._values[self._traceidcodes == 2].max()
            # a bit weird calculation of mean but kept for backward compatibility
            self._values[self._traceidcodes == 2] = newvalue
            return 0.5 * (minval + maxval)

        return None

    def get_xy_value_from_ij(self, iloc, jloc, ixline=False, zerobased=False):
        """Returns x, y from a single i j location.

        Args:
            iloc (int): I (col) location (base is 1)
            jloc (int): J (row) location (base is 1)
            ixline (bool): If True, then input locations are inline and xline position
            zerobased (bool): If True, first index is 0, else it is 1. This does not
                apply when ixline is set to True.

        Returns:
            The z value at location iloc, jloc, None if undefined cell.
        """
        xval, yval = _cube_utils.get_xy_value_from_ij(
            self, iloc, jloc, ixline=ixline, zerobased=zerobased
        )
        return xval, yval

    # =========================================================================
    # Cube extractions, e.g. XSection
    # =========================================================================

    def get_randomline(
        self,
        fencespec,
        zmin=None,
        zmax=None,
        zincrement=None,
        hincrement=None,
        atleast=5,
        nextend=2,
        sampling="nearest",
    ):
        """Get a randomline from a fence spesification.

        This randomline will be a 2D numpy with depth/time on the vertical
        axis, and length along as horizontal axis. Undefined values will have
        the np.nan value.

        The input fencespec is either a 2D numpy where each row is X, Y, Z, HLEN,
        where X, Y are UTM coordinates, Z is depth/time, and HLEN is a
        length along the fence, or a Polygons instance.

        If input fencspec is a numpy 2D, it is important that the HLEN array
        has a constant increment and ideally a sampling that is less than the
        Cube resolution. If a Polygons() instance, this is automated!

        Args:
            fencespec (:obj:`~numpy.ndarray` or :class:`~xtgeo.xyz.polygons.Polygons`):
                2D numpy with X, Y, Z, HLEN as rows or a xtgeo Polygons() object.
            zmin (float): Minimum Z (default is Cube Z minima/origin)
            zmax (float): Maximum Z (default is Cube Z maximum)
            zincrement (float): Sampling vertically, default is Cube ZINC/2
            hincrement (float or bool): Resampling horizontally. This applies only
                if the fencespec is a Polygons() instance. If None (default),
                the distance will be deduced automatically.
            atleast (int): Minimum number of horizontal samples (only if
                fencespec is a Polygons instance)
            nextend (int): Extend with nextend * hincrement in both ends (only if
                fencespec is a Polygons instance)
            sampling (str): Algorithm, 'nearest' or 'trilinear' (first is
                faster, second is more precise for continuous fields)

        Returns:
            A tuple: (hmin, hmax, vmin, vmax, ndarray2d)

        Raises:
            ValueError: Input fence is not according to spec.

        .. versionchanged:: 2.1 support for Polygons() as fencespec, and keywords
           hincrement, atleast and sampling

        .. seealso::
           Class :class:`~xtgeo.xyz.polygons.Polygons`
              The method :meth:`~xtgeo.xyz.polygons.Polygons.get_fence()` which can be
              used to pregenerate `fencespec`

        """
        if not isinstance(fencespec, (np.ndarray, xtgeo.Polygons)):
            raise ValueError(
                "fencespec must be a numpy or a Polygons() object. "
                "Current type is {}".format(type(fencespec))
            )
        logger.info("Getting randomline...")
        res = _cube_utils.get_randomline(
            self,
            fencespec,
            zmin=zmin,
            zmax=zmax,
            zincrement=zincrement,
            hincrement=hincrement,
            atleast=atleast,
            nextend=nextend,
            sampling=sampling,
        )
        logger.info("Getting randomline... DONE")
        return res

    # =========================================================================
    # Import and export
    # =========================================================================

    def from_file(self, sfile, fformat="guess", engine="segyio"):
        """Import cube data from file.

        If fformat is not provided, the file type will be guessed based
        on file extension (e.g. segy og sgy for SEGY format)

        Args:
            sfile (str): Filename (as string or pathlib.Path instance).
            fformat (str): file format guess/segy/rms_regular/xtgregcube
                where 'guess' is default. Regard 'xtgrecube' format as experimental.
            engine (str): For the SEGY reader, 'xtgeo' is builtin
                while 'segyio' uses the SEGYIO library (default).
            deadtraces (float): Set 'dead' trace values to this value (SEGY
                only). Default is UNDEF value (a very large number).

        Raises:
            OSError: if the file cannot be read (e.g. not found)
            ValueError: Input is invalid

        Example::

            >>> zz = Cube()
            >>> zz.from_file('some.segy')


        """
        fobj = xtgeosys._XTGeoFile(sfile)
        fobj.check_file(raiseerror=OSError)

        _, fext = fobj.splitext(lower=True)

        if fformat == "guess":
            if not fext:
                raise ValueError("File extension for Cube missing while fformat==guess")

            fformat = fext.lower()

        if "rms" in fformat:
            _cube_import.import_rmsregular(self, fobj.name)
        elif fformat in ("segy", "sgy"):
            _cube_import.import_segy(self, fobj.name, engine=engine)
        elif fformat == "storm":
            _cube_import.import_stormcube(self, fobj.name)
        elif fformat == "xtgregcube":
            # experimental format
            _cube_import.import_xtgregcube(self, fobj)
        else:
            raise ValueError(f"File format fformat={fformat} is not supported")

        self._filesrc = fobj.name
        self._metadata.required = self

    def to_file(self, sfile, fformat="segy", pristine=False, engine="xtgeo"):
        """Export cube data to file.

        Args:
            sfile (str): Filename
            fformat (str, optional): file format 'segy' (default) or
                'rms_regular'
            pristine (bool): If True, make SEGY from scratch.
            engine (str): Which "engine" to use.

        Example::
            >>> zz = Cube('some.segy')
            >>> zz.to_file('some.rmsreg')
        """
        fobj = xtgeosys._XTGeoFile(sfile, mode="wb")

        fobj.check_folder(raiseerror=OSError)

        if fformat == "segy":
            _cube_export.export_segy(self, fobj.name, pristine=pristine, engine=engine)
        elif fformat == "rms_regular":
            _cube_export.export_rmsreg(self, fobj.name)
        elif fformat == "xtgregcube":
            _cube_export.export_xtgregcube(self, fobj.name)
        else:
            raise ValueError(f"File format fformat={fformat} is not supported")

    def from_roxar(self, project, name, folder=None):  # pragma: no cover
        """Import (transfer) a cube from a Roxar seismic object to XTGeo.

        Args:
            project (str): Inside RMS use the magic 'project', else use
                path to RMS project
            name (str): Name of cube within RMS project.
            folder (str): Folder name in in RMS if present; use '/' to seperate
                subfolders

        Raises:
            To be described...

        Example::

            zz = Cube()
            zz.from_roxar(project, 'truth_reek_seismic_depth_2000', folder="alt/depth")

        """
        _cube_roxapi.import_cube_roxapi(self, project, name, folder=folder)

        self._metadata.required = self

    def to_roxar(
        self, project, name, folder=None, domain="time", compression=("wavelet", 5)
    ):  # pragma: no cover
        """Export (transfer) a cube from a XTGeo cube object to Roxar data.

        Note:
            When project is file path (direct access, outside RMS) then
            ``to_roxar()`` will implicitly do a project save. Otherwise, the project
            will not be saved until the user do an explicit project save action.

        Args:
            project (str or roxar._project): Inside RMS use the magic 'project',
                else use path to RMS project, or a project reference
            name (str): Name of cube (seismic data) within RMS project.
            folder (str): Cubes may be stored under a folder in the tree, use '/'
                to seperate subfolders.
            domain (str): 'time' (default) or 'depth'
            compression (tuple): description to come...

        Raises:
            To be described...

        Example::

            zz = xtgeo.cube.Cube('myfile.segy')
            zz.to_roxar(project, 'reek_cube')

            # alternative
            zz = xtgeo.cube_from_file('myfile.segy')
            zz.to_roxar(project, 'reek_cube')

        """
        _cube_roxapi.export_cube_roxapi(
            self, project, name, folder=folder, domain=domain, compression=compression
        )

    @staticmethod
    def scan_segy_traces(sfile, outfile=None):
        """Scan a SEGY file traces and print limits info to STDOUT or file.

        Args:
            sfile (str): Name of SEGY file
            outfile: File where store scanned trace info, if empty or None
                output goes to STDOUT.
        """
        oflag = False
        # if outfile is none, it means that you want to plot on STDOUT
        if outfile is None:
            fx = tempfile.NamedTemporaryFile(delete=False, prefix="tmpxgeo")
            fx.close()
            outfile = fx.name
            logger.info("TMP file name is %s", outfile)
            oflag = True

        _cube_import._import_segy_xtgeo(
            sfile, scanheadermode=False, scantracemode=True, outfile=outfile
        )

        if oflag:
            # pass
            logger.info("OUTPUT to screen...")
            with open(outfile, "r") as out:
                for line in out:
                    print(line.rstrip("\r\n"))
            os.remove(outfile)

    @staticmethod
    def scan_segy_header(sfile, outfile=None):
        """Scan a SEGY file header and print info to screen or file.

        Args:
            sfile (str): Name of SEGY file
            outfile (str): File where store header info, if empty or None
                output goes to screen (STDOUT).
        """
        flag = False
        # if outfile is none, it means that you want to print on STDOUT
        if outfile is None:
            fc = tempfile.NamedTemporaryFile(delete=False, prefix="tmpxtgeo")
            fc.close()
            outfile = fc.name
            logger.info("TMP file name is %s", outfile)
            flag = True

        _cube_import._import_segy_xtgeo(
            sfile, scanheadermode=True, scantracemode=False, outfile=outfile
        )

        if flag:
            logger.info("OUTPUT to screen...")
            with open(outfile, "r") as out:
                for line in out:
                    print(line.rstrip("\r\n"))
            os.remove(outfile)

    def _ensure_correct_values(self, values):
        """Ensures that values is a 3D numpy (ncol, nrow, nlay), C order.

        Args:
            values (array-like or scalar): Values to process.

        Return:
            Nothing, self._values will be updated inplace

        """
        if values is None or values is False:
            self._ensure_correct_values(0.0)
            return

        if isinstance(values, numbers.Number):
            self._values = np.zeros(self.dimensions, dtype=np.float32) + values
            return

        if isinstance(values, np.ndarray):
            values = values.reshape(self.dimensions)

            if not values.data.c_contiguous:
                values = np.ascontiguousarray(values)

        if isinstance(values, (list, tuple)):
            values = np.array(values, dtype=np.float32).reshape(self.dimensions)

        self._values = values
