# Installation path for psrad
export PSRAD_PATH='/home/mpim/m300580/icon/icon-aes/psrad'

# Environment settings
export F90="gfortran"  # FORTRAN compiler
export HDF5ROOT="/sw/jessie-x64/hdf5-1.8.16-gccsys"
export NETCDFROOT="/sw/jessie-x64/netcdf-4.3.3.1-gccsys"
export NETCDFFROOT="/sw/jessie-x64/netcdf_fortran-4.4.2-gccsys"
export LD_LIBRARY_PATH="${HDF5ROOT}/lib:${LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH="${NETCDFROOT}/lib:${LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH="${NETCDFFROOT}/lib:${LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:${PSRAD_PATH}"

# Include installation path to PATH (needed for bash).
export PATH="${PATH}:${PSRAD_PATH}"

# **Dirty** workaround
export HDF5_DISABLE_VERSION_CHECK=1