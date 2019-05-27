# -*- coding: utf-8 -*-
"""This module contains a choice of convective adjustments, which can be used
in the RCE simulations.

**Example**

Create an instance of a convective adjustment class, *e.g.* the relaxed
adjustment class, and use it in an RCE simulation.
    >>> import konrad
    >>> relaxed_convection=konrad.convection.RelaxedAdjustment()
    >>> rce = konrad.RCE(atmosphere=..., convection=relaxed_convection)
    >>> rce.run()

Currently there are two convective classes that can be used,
:py:class:`HardAdjustment` and :py:class:`RelaxedAdjustment`, and one class
which can be used and does nothing, :py:class:`NonConvective`.
"""
import abc

import numpy as np
import typhon
from typhon.physics import vmr2mixing_ratio
from scipy.interpolate import interp1d

from konrad import constants
from konrad.component import Component
from konrad.surface import SurfaceFixedTemperature


__all__ = [
    'energy_difference_dry',
    'latent_heat_difference',
    'interp_variable',
    'pressure_lapse_rate',
    'update_temporary_atmosphere',
    'water_vapour_profile',
    'Convection',
    'NonConvective',
    'HardAdjustment',
    'RelaxedAdjustment',
]


def energy_difference_dry(T_2, T_1, sst_2, sst_1, phlev, Cp, eff_Cp_s):
    """
    Calculate the energy difference between two atmospheric profiles (2 - 1).

    Parameters:
        T_2: atmospheric temperature profile (2)
        T_1: atmospheric temperature profile (1)
        sst_2: surface temperature (2)
        sst_1: surface temperature (1)
        phlev: pressure half-levels [Pa]
            must be the same for both atmospheric profiles
        Cp: Specific isobaric heat capacity of the atmosphere.
        eff_Cp_s: effective heat capacity of surface
    """
    g = constants.g

    dT = T_2 - T_1  # convective temperature change of atmosphere
    dT_s = sst_2 - sst_1  # of surface

    term_diff = - np.sum(Cp/g * dT * np.diff(phlev)) + eff_Cp_s * dT_s

    return term_diff


def latent_heat_difference(h2o_2, h2o_1):
    """
    Calculate the difference in energy from latent heating between two
    water vapour profiles (2 - 1).

    Parameters:
        h2o_2 (ndarray): water vapour content [kg m^-2]
        h2o_1 (ndarray): water vapour content [kg m^-2]
    Returns:
        float: energy difference [J m^-2]
    """

    Lv = constants.Lv  # TODO: include pressure/temperature dependence?
    term_diff = np.sum((h2o_2-h2o_1) * Lv)

    return term_diff


def interp_variable(variable, convective_heating, lim):
    """
    Find the value of a variable corresponding to where the convective
    heating equals a certain specified value (lim).

    Parameters:
        variable (ndarray): variable to be interpolated
        convective_heating (ndarray): interpolate based on where this variable
            equals 'lim'
        lim (float/int): value of 'convective_heating' used to find the
            corresponding value of 'variable'

    Returns:
         float: interpolated value of 'variable'
    """
    positive_i = int(np.argmax(convective_heating > lim))
    contop_index = int(np.argmax(
        convective_heating[positive_i:] < lim)) + positive_i

    # Create auxiliary arrays storing the Qr, T and p values above and below
    # the threshold value. These arrays are used as input for the interpolation
    # in the next step.
    heat_array = np.array([convective_heating[contop_index - 1],
                           convective_heating[contop_index]])
    var_array = np.array([variable[contop_index - 1], variable[contop_index]])

    # Interpolate the values to where the convective heating rate equals `lim`.
    return interp1d(heat_array, var_array)(lim)


def pressure_lapse_rate(p, phlev, T, lapse):
    """
    Calculate the pressure lapse rate (change in temperature with pressure)
    from the height lapse rate (change in temperature with height).

    Parameters:
        p (ndarray): pressure levels
        phlev (ndarray): pressure half-levels
        T (ndarray): temperature profile
        lapse (ndarray): lapse rate [K/m] defined on pressure half-levels
    Returns:
        ndarray: pressure lapse rate [K/Pa]
    """
    density_p = typhon.physics.density(p, T)
    # Interpolate density onto pressure half-levels
    density = interp1d(p, density_p, fill_value='extrapolate')(phlev[:-1])

    g = constants.earth_standard_gravity
    lp = -lapse / (g * density)
    return lp


def update_temporary_atmosphere(atmosphere, T, humidity):
    """
    Update atmospheric temperature, corresponding water vapour content,
    and height.

    Parameters:
        atmosphere (konrad.atmosphere): atmosphere model to be updated
        T (ndarray): temperature profile
        humidity (konrad.humidity): humidity model
    """
    atmosphere['T'][-1] = T
    humidity.adjust_humidity(
        atmosphere=atmosphere,
    )
    atmosphere.update_height()
    return


def water_vapour_profile(atmosphere):
    """Calculate the mass of water vapour in each model layer

    Parameters:
        atmosphere (konrad.atmosphere): atmosphere model
    Returns:
        ndarray: atmospheric water vapour content [kg m^-2]
    """

    h2o = vmr2mixing_ratio(atmosphere['H2O'][-1])

    rho = typhon.physics.density(
        atmosphere['plev'], atmosphere['T'][-1])  # kg m-3
    z = atmosphere.get('z')[-1]  # m
    dz = np.gradient(z)  # TODO: gradient or calculate diff from half levels?
    h2o *= rho * dz  # kg m-2

    return h2o


class Convection(Component, metaclass=abc.ABCMeta):
    """Base class to define abstract methods for convection schemes."""
    @abc.abstractmethod
    def stabilize(self, atmosphere, atmosphere_old, humidity, lapse, surface,
                  timestep):
        """Stabilize the temperature profile by redistributing energy.

        Parameters:
            atmosphere (konrad.atmosphere): atmosphere model
            atmosphere_old (konrad.atmosphere): atmosphere model with properties
                of previous timestep
            humidity (konrad.humidity): humidity model
            lapse (ndarray): Temperature lapse rate [K/day].
            surface (konrad.surface): Surface model.
            timestep (float): Timestep width [day].
        """


class NonConvective(Convection):
    """Do not apply convection."""
    def stabilize(self, *args, **kwargs):
        pass


class HardAdjustment(Convection):
    """Instantaneous adjustment of temperature profiles"""
    def stabilize(self, atmosphere, atmosphere_old, humidity, lapse, surface,
                  timestep):

        T_rad = atmosphere['T'][0, :]
        p = atmosphere['plev']

        # Find convectively adjusted temperature profile.
        T_new, T_s_new = self.convective_adjustment(
            atmosphere,
            atmosphere_old,
            humidity,
            lapse=lapse,
            surface=surface,
            T_old=T_old,
            timestep=timestep,
        )
        # get convective top temperature and pressure
        self.update_convective_top(T_rad, T_new, p, timestep=timestep)
        # Update atmospheric temperatures as well as surface temperature.
        atmosphere['T'][0, :] = T_new
        surface['temperature'][0] = T_s_new

    def convective_adjustment(self, atmosphere, atmosphere_old, humidity,
                              lapse, surface, timestep=0.1):
        """
        Find the energy-conserving temperature profile using upper and lower
        bound profiles (calculated from surface temperature extremes: no change
        for upper bound and coldest atmospheric temperature for lower bound)
        and an iterative procedure between them.
        Return the atmospheric temperature profile which satisfies energy
        conservation.

        Parameters:
            atmosphere (konrad.atmosphere): atmosphere model updated with the
                radiative heating rates for the current timestep
            atmosphere_old (konrad.atmosphere): atmosphere model at the
                previous timestep
            humidity (konrad.humidity): humidity model
            lapse (ndarray): critical lapse rate [K/m] defined on pressure
                half-levels
            surface (konrad.surface):
<<<<<<< HEAD
                surface associated with the radiatively adjusted temperature
                profile
            timestep (float): only required for slow convection [days]

        Returns:
            ndarray: atmospheric temperature profile [K]
            float: surface temperature [K]
=======
                surface associated with old temperature profile
            T_old (ndarray): temperature profile of previous timestep
                only used in relaxed convection with tau(T)
            timestep (float): only required for relaxed convection
        """
        p = atmosphere['plev']
        phlev = atmosphere['phlev']
        T_rad = atmosphere['T'][-1]

        lp = pressure_lapse_rate(p, phlev, T_rad, lapse)

        # This is the temperature profile required if we have a set-up with a
        # fixed surface temperature. In this case, energy is not conserved.
        if isinstance(surface, SurfaceFixedTemperature):
            T_con = self.convective_profile(
                T_rad, p, phlev, surface['temperature'], lp, timestep=timestep)
            return T_con, surface['temperature']

        # Otherwise we should conserve energy --> our energy change should be
        # less than the threshold 'near_zero'.
        # The threshold is scaled with the effective heat capacity of the
        # surface, ensuring that very thick surfaces reach the target.
        near_zero = float(surface.heat_capacity / 1e13)

        # Find the energy difference if there is no change to surface temp due
        # to convective adjustment. In this case the new profile should be
        # associated with an increase in energy in the atmosphere.
        surfaceTpos = surface['temperature']
        T_con, diff_pos = self.create_and_check_profile(
            atmosphere, atmosphere_old, humidity,
            surface, surfaceTpos, lp, timestep=timestep)

        # For other cases, if we find a decrease or approx no change in energy,
        # the atmosphere is not being warmed by the convection,
        # as it is not unstable to convection, so no adjustment is applied.
        if diff_pos < near_zero:
            return T_con, surface['temperature']

        # If the atmosphere is unstable to convection, a fixed surface
        # temperature produces an increase in energy, as convection warms the
        # atmosphere. Therefore 'surfaceTpos' is an upper bound for the
        # energy-conserving surface temperature we are trying to find.
        # Taking the surface temperature as the coldest temperature in the
        # radiative profile gives us a lower bound. In this case, convection
        # would not warm the atmosphere, so we do not change the atmospheric
        # temperature profile and calculate the energy change simply from the
        # surface temperature change.
        surfaceTneg = np.array([np.min(T_rad)])
        eff_Cp_s = surface.heat_capacity
        diff_neg = eff_Cp_s * (surfaceTneg - surface['temperature'])
        if np.abs(diff_neg) < near_zero:
            return T_con, surfaceTneg

        # Now we have a upper and lower bound for the surface temperature of
        # the energy conserving profile. Iterate to get closer to the energy-
        # conserving temperature profile.
        counter = 0
        while diff_pos >= near_zero and np.abs(diff_neg) >= near_zero:
            # Use a surface temperature between our upper and lower bounds and
            # closer to the bound associated with a smaller energy change.
            surfaceT = (surfaceTneg + (surfaceTpos - surfaceTneg)
                        * (-diff_neg) / (-diff_neg + diff_pos))
            # Calculate temperature profile and energy change associated with
            # this surface temperature.
            T_con, diff = self.create_and_check_profile(
                atmosphere, atmosphere_old, humidity,
                surface, surfaceT, lp, timestep=timestep)

            # Update either upper or lower bound.
            if diff > 0:
                diff_pos = diff
                surfaceTpos = surfaceT
            else:
                diff_neg = diff
                surfaceTneg = surfaceT

            # to avoid getting stuck in a loop if something weird is going on
            counter += 1
            if counter == 100:
                raise ValueError(
                    "No energy conserving convective profile can be found"
                )

        return T_con, surfaceT

    def convective_profile(self, T_rad, p, phlev, surfaceT, lp, **kwargs):

        """
        Assuming a particular surface temperature (surfaceT), create a new
        profile, following the specified lapse rate (lp) for the region where
        the convectively adjusted atmosphere is warmer than the radiative one.
        Above this, use the radiative profile, as convection is not allowed in
        the stratosphere.

        Parameters:
            T_rad (ndarray): radiative temperature profile [K]
            p (ndarray): pressure levels [Pa]
            phlev (ndarray): pressure half-levels [Pa]
            surfaceT (float): surface temperature [K]
            lp (ndarray): pressure lapse rate [K/Pa]

        Returns:
             ndarray: convectively adjusted temperature profile [K]
        """
        # for the lapse rate integral use a different dp, considering that the
        # lapse rate is given on half levels
        dp_lapse = np.hstack((np.array([p[0] - phlev[0]]), np.diff(p)))
        T_con = surfaceT - np.cumsum(dp_lapse * lp)

        if np.any(T_con > T_rad):
            contop = np.max(np.where(T_con > T_rad))
            T_con[contop+1:] = T_rad[contop+1:]
        else:
            # convective adjustment is only applied to the atmospheric profile,
            # if it causes heating somewhere
            T_con = T_rad

        return T_con

    def create_and_check_profile(self, atmosphere, atmosphere_old, humidity,
                                 surface, surfaceT, lp, timestep=0.1):
        """
        Create a convectively adjusted temperature profile and calculate how
        close it is to satisfying energy conservation.

        Parameters:
            atmosphere (konrad.atmosphere): atmosphere model updated with the
                radiative heating rates for the current timestep
            atmosphere_old (konrad.atmosphere): atmosphere model at the
                previous timestep
            humidity (konrad.humidity): humidity model
            surface (konrad.surface):
                surface associated with the radiatively adjusted temperature
                profile
            surfaceT (float): surface temperature of the new profile
            lp (ndarray): lapse rate in K/Pa
            timestep (float): not required in this case

        Returns:
            ndarray: new atmospheric temperature profile
            float: energy difference between the new profile and the radiatively
                adjusted one
        """
        p = atmosphere['plev']
        phlev = atmosphere['phlev']
        T_rad = atmosphere['T'][-1]
        T_old = atmosphere_old['T'][-1]

        T_con = self.convective_profile(T_rad, p, phlev, surfaceT, lp,
                                        timestep=timestep, T_old=T_old)

        eff_Cp_s = surface.heat_capacity

        atmosphere_con = atmosphere.copy()
        update_temporary_atmosphere(atmosphere_con, T_con, humidity)

        h2o_old = water_vapour_profile(atmosphere_old)
        h2o_new = water_vapour_profile(atmosphere_con)

        # difference in energy due to temperature change between radiatively
        # and convectively adjusted profiles
        diff = energy_difference_dry(
            T_con, T_rad, surfaceT, surface['temperature'], phlev,
            atmosphere.get_heat_capacity(), eff_Cp_s)

        # difference due to latent heating between previous timestep and
        # current timestep
        wet_diff = latent_heat_difference(h2o_new, h2o_old)

        diff += wet_diff

        return T_con, float(diff)

    def update_convective_top(self, T_rad, T_con, p, timestep=0.1, lim=0.2):
        """
        Find the pressure and temperature where the radiative heating has a
        certain value.

        Note:
            In the HardAdjustment case, for a contop temperature that is not
            dependent on the number or distribution of pressure levels, it is
            better to take a value of lim not equal or very close to zero.

        Parameters:
            T_rad (ndarray): radiative temperature profile [K]
            T_con (ndarray): convectively adjusted temperature profile [K]
            p (ndarray): model pressure levels [Pa]
            timestep (float): model timestep [days]
            lim (float): Threshold value [K/day].
        """
        convective_heating = (T_con - T_rad) / timestep
        self.create_variable('convective_heating_rate', convective_heating)

        if np.any(convective_heating > lim):  # if there is convective heating
            # find the values of pressure and temperature at the convective top
            contop_p = interp_variable(p, convective_heating, lim)
            contop_T = interp_variable(T_con, convective_heating, lim)
            contop_index = interp_variable(
                np.arange(0, p.shape[0]), convective_heating, lim
            )

        else:  # if there is no convective heating
            contop_index, contop_p, contop_T = np.nan, np.nan, np.nan

        for name, value in [('convective_top_plev', contop_p),
                            ('convective_top_temperature', contop_T),
                            ('convective_top_index', contop_index),
                            ]:
            self.create_variable(name, np.array([value]))

        return

    def update_convective_top_height(self, z, lim=0.2):
        """Find the height where the radiative heating has a certain value.

        Parameters:
            z (ndarray): height array [m]
            lim (float): Threshold convective heating value [K/day]
        """
        convective_heating = self.get('convective_heating_rate')[0]
        if np.any(convective_heating > lim):  # if there is convective heating
            contop_z = interp_variable(z, convective_heating, lim=lim)
        else:  # if there is no convective heating
            contop_z = np.nan
        self.create_variable('convective_top_height', np.array([contop_z]))
        return


class RelaxedAdjustment(HardAdjustment):
    """Adjustment with relaxed convection in upper atmosphere.

    This convection scheme allows for a transition regime between a
    convectively driven troposphere and the radiatively balanced stratosphere.
    """
    def __init__(self, tau=None):
        """
        Parameters:
            tau (ndarray): Array of convective timescale values [days]
        """
        self.convective_tau = tau

    def get_convective_tau(self, p, **kwargs):
        """Return a convective timescale profile.

        Parameters:
            p (ndarray): Pressure levels [Pa].

        Returns:
            ndarray: Convective timescale profile [days].
        """
        if self.convective_tau is not None:
            return self.convective_tau

        tau0 = 1/24  # 1 hour
        tau = tau0*np.exp(p[0] / p)

        return tau

    def convective_profile(self, T_rad, p, phlev, surfaceT, lp, timestep,
                           T_old):
        """
        Assuming a particular surface temperature (surfaceT), create a new
        profile, which tries to follow the specified lapse rate (lp). How close
        it gets to following the specified lapse rate depends on the convective
        timescale and model timestep.

        Parameters:
            T_rad (ndarray): radiative temperature profile [K]
            p (ndarray): pressure levels [Pa]
            phlev (ndarray): pressure half-levels [Pa]
            surfaceT (float): surface temperature [K]
            lp (ndarray): pressure lapse rate [K/Pa]
            timestep (float/int): model timestep [days]

        Returns:
             ndarray: convectively adjusted temperature profile [K]
        """
        # For the lapse rate integral use a dp, which takes into account that
        # the lapse rate is given on the model half-levels.
        dp_lapse = np.hstack((np.array([p[0] - phlev[0]]), np.diff(p)))

        tau = self.get_convective_tau(p, T_old=T_old)

        tf = 1 - np.exp(-timestep / tau)
        T_con = T_rad * (1 - tf) + tf * (surfaceT - np.cumsum(dp_lapse * lp))

        return T_con


class RelaxedTauT(RelaxedAdjustment):
    """Adjustment with relaxed convection in upper atmosphere.
    The convective timescale is kept constant with temperature.
    """
    def __init__(self, tau=None):
        """
        Parameters:
            tau (ndarray): Array of convective timescale values [days]
        """
        self.convective_tau = tau
        self.tau_function = None

    def get_convective_tau(self, p, T_old):
        """Return a convective timescale profile.

        Parameters:
            p (ndarray): Pressure levels [Pa].
            T_old (ndarray): Temperature [K]

        Returns:
            ndarray: Convective timescale profile [days].
        """
        if self.convective_tau is None:  # first time only if not specified
            tau0 = 1 / 24  # 1 hour
            self.convective_tau = tau0 * np.exp(p[0] / p)
        if self.tau_function is None:  # first time only
            self.tau_function = interp1d(T_old, self.convective_tau)

        return self.tau_function(T_old)
