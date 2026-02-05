
!--------------------------------------------------------------------------
!
!    Copyright (C) 2026  Georg Umgiesser
!
!    This file is part of SHYFEM.
!
!    SHYFEM is free software: you can redistribute it and/or modify
!    it under the terms of the GNU General Public License as published by
!    the Free Software Foundation, either version 3 of the License, or
!    (at your option) any later version.
!
!    SHYFEM is distributed in the hope that it will be useful,
!    but WITHOUT ANY WARRANTY; without even the implied warranty of
!    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
!    GNU General Public License for more details.
!
!    You should have received a copy of the GNU General Public License
!    along with SHYFEM. Please see the file COPYING in the main directory.
!    If not, see <http://www.gnu.org/licenses/>.
!
!--------------------------------------------------------------------------

! Module containing authoritative physical constants for SHYFEM
!
! This module centralizes physical constants that were previously
! defined with varying precision across multiple files.
!
! Usage:
!   use mod_physical_constants, only: pi_dp, grav_dp
!   use mod_physical_constants, only: pi => pi_sp  ! for single precision alias
!
! revision log:
!
! 04.02.2026	ggu	created to centralize physical constants
! 05.02.2026	ggu	extended with more constants

!==================================================================
	module mod_physical_constants
!==================================================================

	implicit none

	!------------------------------------------------------------
	! Mathematical constants (double precision)
	!------------------------------------------------------------

	double precision, parameter :: pi_dp = 3.14159265358979323846d0
	double precision, parameter :: twopi_dp = 2.d0 * pi_dp
	double precision, parameter :: halfpi_dp = 0.5d0 * pi_dp
	double precision, parameter :: deg2rad_dp = pi_dp / 180.d0
	double precision, parameter :: rad2deg_dp = 180.d0 / pi_dp

	!------------------------------------------------------------
	! Mathematical constants (single precision versions)
	!------------------------------------------------------------

	real, parameter :: pi_sp = 3.14159265358979
	real, parameter :: twopi_sp = 2.0 * pi_sp
	real, parameter :: halfpi_sp = 0.5 * pi_sp
	real, parameter :: deg2rad_sp = pi_sp / 180.0
	real, parameter :: rad2deg_sp = 180.0 / pi_sp

	!------------------------------------------------------------
	! Physical constants (double precision)
	!------------------------------------------------------------

	! Standard acceleration due to gravity (m/s^2)
	! Note: Using 9.81 for backward compatibility with existing simulations
	! Standard value is 9.80665 m/s^2 (exact by definition)
	double precision, parameter :: grav_dp = 9.81d0

	! von Karman constant (dimensionless)
	double precision, parameter :: vonkarman_dp = 0.4d0

	! Stefan-Boltzmann constant (W m^-2 K^-4)
	double precision, parameter :: stefan_boltzmann_dp = 5.670374419d-8

	!------------------------------------------------------------
	! Physical constants (single precision versions)
	!------------------------------------------------------------

	real, parameter :: grav_sp = 9.81
	real, parameter :: vonkarman_sp = 0.4
	real, parameter :: stefan_boltzmann_sp = 5.670374419e-8

	!------------------------------------------------------------
	! Time constants
	!------------------------------------------------------------

	double precision, parameter :: seconds_per_day = 86400.d0
	double precision, parameter :: seconds_per_hour = 3600.d0
	real, parameter :: seconds_per_day_sp = 86400.0
	real, parameter :: seconds_per_hour_sp = 3600.0

	!------------------------------------------------------------
	! Water/Air properties (reference values)
	!------------------------------------------------------------

	! Reference density of seawater (kg/m^3)
	double precision, parameter :: rho_seawater_dp = 1025.d0
	real, parameter :: rho_seawater_sp = 1025.0

	! Reference density of freshwater (kg/m^3)
	double precision, parameter :: rho_freshwater_dp = 1000.d0
	real, parameter :: rho_freshwater_sp = 1000.0

	! Density of air at sea level (kg/m^3)
	double precision, parameter :: rho_air_dp = 1.225d0
	real, parameter :: rho_air_sp = 1.225

!==================================================================
	end module mod_physical_constants
!==================================================================
