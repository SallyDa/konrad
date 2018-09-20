# -*- coding: utf-8 -*-
"""This module contains classes handling different treatments of ozone."""

import abc
import logging
from scipy.interpolate import interp1d

from konrad.component import Component
from konrad.utils import ozone_profile_rcemip, refined_pgrid

__all__ = [
    'Ozone',
    'OzonePressure',
    'OzoneHeight',
    'OzoneNormedPressure',
]

logger = logging.getLogger(__name__)

class Ozone(Component, metaclass=abc.ABCMeta):
    """Base class to define abstract methods for ozone treatments."""

    def __init__(self):
        """
        Parameters:
            initial_ozone (ndarray): initial ozone vmr profile
        """
        self['initial_ozone'] = (('plev',), None)

    @abc.abstractmethod
    def get(self, atmos, timestep, zenith, radheat):
        """Updates the ozone profile within the atmosphere class.

        Parameters:
            atmos (konrad.atmosphere): atmosphere model containing ozone
                concentration profile, height, temperature, pressure and half
                pressure levels at the current timestep
            timestep (float): timestep of run [days]
            zenith (float): solar zenith angle,
                angle of the Sun to the vertical [degrees]
            radheat (ndarray): array of net radiative heating rates
        """

class OzonePressure(Ozone):
    """Ozone fixed with pressure, no adjustment needed."""
    def get(self, **kwargs):
        return


class OzoneHeight(Ozone):
    """Ozone fixed with height."""
    def __init__(self):
        self._f = None

    def get(self, atmos, **kwargs):
        if self._f is None:
            self._f = interp1d(
                atmos['z'][0, :],
                atmos['O3'],
                fill_value='extrapolate',
            )

        atmos['O3'] = (('time', 'plev'), self._f(atmos['z'][0, :]))


class OzoneNormedPressure(Ozone):
    """Ozone shifts with the normalisation level (chosen to be the convective
    top)."""
    def __init__(self, norm_level=None):
        """
        Parameters:
            norm_level (float): pressure for the normalisation
                normally chosen as the convective top pressure at the start of
                the simulation [Pa]
        """
        self.norm_level = norm_level
        self._f = None

    def get(self, atmos, radheat, **kwargs):
        if self.norm_level is None:
            self.norm_level = atmos.get_convective_top(radheat)

        if self._f is None:
            self._f = interp1d(
                atmos['plev'] / self.norm_level,
                atmos['O3'][0, :],
                fill_value='extrapolate',
            )

        norm_new = atmos.get_convective_top(radheat)

        atmos['O3'] = (
            ('time', 'plev'),
            self._f(atmos['plev'] / norm_new).reshape(1, -1)
        )
