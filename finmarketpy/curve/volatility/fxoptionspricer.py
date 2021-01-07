__author__ = 'saeedamen'  # Saeed Amen

#
# Copyright 2016-2020 Cuemacro - https://www.cuemacro.com / @cuemacro
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the
# License. You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#
# See the License for the specific language governing permissions and limitations under the License.
#

import numpy as np
import pandas as pd

from numba import guvectorize
from findatapy.timeseries import Calendar
from findatapy.util import LoggerManager

from finmarketpy.util.marketconstants import MarketConstants
from finmarketpy.curve.abstractpricer import AbstractPricer

from financepy.finutils.FinDate import FinDate
from financepy.models.FinModelBlackScholes import FinModelBlackScholes
from financepy.products.fx.FinFXVanillaOption import FinFXVanillaOption
from financepy.finutils.FinGlobalTypes import FinOptionTypes

market_constants = MarketConstants()

class FXOptionsPricer(AbstractPricer):
    """Prices various vanilla FX options, using FinancePy underneath.
    """

    def __init__(self, fx_vol_surface=None, premium_output=market_constants.fx_options_premium_output,
                 delta_output=market_constants.fx_options_delta_output):

        self._calendar = Calendar()
        self._fx_vol_surface = fx_vol_surface
        self._premium_output = premium_output
        self._delta_output = delta_output

    def price_instrument(self, cross, horizon_date, strike, expiry_date=None, vol=None, notional=1000000,
                         contract_type='european-call', tenor=None,
                         fx_vol_surface=None, premium_output=None, delta_output=None, depo_tenor=None):
        """Prices FX options for horizon dates/expiry dates given by the user from FX spot rates, FX volatility surface
        and deposit rates.

        Parameters
        ----------
        cross : str
            Currency pair

        horizon_date : DateTimeIndex
            Horizon dates for options

        expiry_date : DateTimeIndex
            expiry dates for options

        market_df : DataFrame
            Contains FX spot, FX vol surface quotes, FX forwards and base depos

        Returns
        -------
        DataFrame
        """

        # if market_df is None: market_df = self._market_df
        if fx_vol_surface is None: fx_vol_surface = self._fx_vol_surface
        if premium_output is None: premium_output = self._premium_output
        if delta_output is None: delta_output = self._delta_output

        logger = LoggerManager().getLogger(__name__)

        field = fx_vol_surface._field

        # Make horizon date and expiry date pandas DatetimeIndex
        if isinstance(horizon_date, pd.Timestamp):
            horizon_date = pd.DatetimeIndex([horizon_date])
        else:
            horizon_date = pd.DatetimeIndex(horizon_date)

        if expiry_date is not None:
            if isinstance(expiry_date, pd.Timestamp):
                expiry_date = pd.DatetimeIndex([expiry_date])
            else:
                expiry_date = pd.DatetimeIndex(expiry_date)
        else:
            expiry_date = self._calendar.get_expiry_date_from_horizon_date(horizon_date, tenor, cal=cross)

        # If the strike hasn't been supplied need to work this out
        if not(isinstance(strike, np.ndarray)):
            old_strike = strike

            if isinstance(strike, str):
                strike = np.empty(len(horizon_date), dtype=object)
            else:
                strike = np.empty(len(horizon_date))

            strike.fill(old_strike)

        # If the vol hasn't been supplied need to work this out
        if not(isinstance(vol, np.ndarray)):

            if vol is None:
                vol = np.nan

            old_vol = vol

            vol = np.empty(len(horizon_date))
            vol.fill(old_vol)

        option_values = np.empty(len(horizon_date))
        spot = np.empty(len(horizon_date))
        delta = np.empty(len(horizon_date))
        intrinsic_values = np.empty(len(horizon_date))

        if contract_type == 'european-call':
            contract_type_fin = FinOptionTypes.EUROPEAN_CALL
        elif contract_type == 'european-put':
            contract_type_fin = FinOptionTypes.EUROPEAN_PUT
        elif contract_type == 'european-straddle':
            pass

        for i in range(len(expiry_date)):
            built_vol_surface = False

            # If we have a "key strike" need to fit the vol surface
            if isinstance(strike[i], str):
                fx_vol_surface.build_vol_surface(horizon_date[i], depo_tenor=depo_tenor)
                fx_vol_surface.extract_vol_surface(num_strike_intervals=None)

                built_vol_surface = True

                if strike[i] == 'atm': strike[i] = fx_vol_surface.get_atm_strike(tenor)
                elif strike[i] == '25d-otm':
                    if 'call' in contract_type:
                        strike[i] = fx_vol_surface.get_25d_call_strike(tenor)
                    elif 'put' in contract_type:
                        strike[i] = fx_vol_surface.get_25d_put_strike(tenor)
                elif strike[i] == '10d-otm':
                        if 'call' in contract_type:
                            strike[i] = fx_vol_surface.get_10d_call_strike(tenor)
                        elif 'put' in contract_type:
                            strike[i] = fx_vol_surface.get_10d_put_strike(tenor)

            # If an implied vol hasn't been provided, interpolate that one, fit the vol surface (if hasn't already been
            # done)
            if np.isnan(vol[i]):
                if not(built_vol_surface):
                    fx_vol_surface.build_vol_surface(horizon_date[i])
                    fx_vol_surface.extract_vol_surface(num_strike_intervals=None)

                if tenor is None:
                    vol[i] = fx_vol_surface.calculate_vol_for_strike_expiry(strike[i], expiry_date=expiry_date[i], tenor=None)
                else:
                    vol[i] = fx_vol_surface.calculate_vol_for_strike_expiry(strike[i], expiry_date=None, tenor=tenor)

            model = FinModelBlackScholes(float(vol[i]))

            logger.info("Pricing " + contract_type + " option, horizon date = " + str(horizon_date[i]) + ", expiry date = "
                         + str(expiry_date[i]))

            option = FinFXVanillaOption(self._findate(expiry_date[i]), strike[i],
                                        cross, contract_type_fin, notional, cross[0:3])

            spot[i] = fx_vol_surface.get_spot()

            """ FinancePy will return the value in the following dictionary for values
                {'v': vdf,
                "cash_dom": cash_dom,
                "cash_for": cash_for,
                "pips_dom": pips_dom,
                "pips_for": pips_for,
                "pct_dom": pct_dom,
                "pct_for": pct_for,
                "not_dom": notional_dom,
                "not_for": notional_for,
                "ccy_dom": self._domName,
                "ccy_for": self._forName}
            """

            option_values[i] = option.value(self._findate(horizon_date[i]),
                                            spot[i], fx_vol_surface.get_dom_discount_curve(),
                                            fx_vol_surface.get_for_discount_curve(),
                                            model)[premium_output.replace('-', '_')]

            intrinsic_values[i] = option.value(self._findate(expiry_date[i]),
                                            spot[i], fx_vol_surface.get_dom_discount_curve(),
                                            fx_vol_surface.get_for_discount_curve(),
                                            model)[premium_output.replace('-', '_')]

            """FinancePy returns this dictionary for deltas
                {"pips_spot_delta": pips_spot_delta,
                "pips_fwd_delta": pips_fwd_delta,
                "pct_spot_delta_prem_adj": pct_spot_delta_prem_adj,
                "pct_fwd_delta_prem_adj": pct_fwd_delta_prem_adj}
            """

            delta[i] = option.delta(self._findate(horizon_date[i]),
                        spot[i], fx_vol_surface.get_dom_discount_curve(),
                        fx_vol_surface.get_for_discount_curve(), model)[delta_output.replace('-', '_')]

        option_prices_df = pd.DataFrame(index=horizon_date)

        option_prices_df[cross + '-option-price.' + field] = option_values
        option_prices_df[cross + '.' + field] = spot
        option_prices_df[cross + '-strike.' + field] = strike
        option_prices_df[cross + '-vol.' + field] = vol
        option_prices_df[cross + '-delta.' + field] = delta
        option_prices_df[cross + '.expiry-date'] = expiry_date
        option_prices_df[cross + '-intrinsic-value.' + field] = intrinsic_values

        return option_prices_df

    def get_day_count_conv(self, currency):
        if currency in market_constants.currencies_with_365_basis:
            return 365.0

        return 360.0

    def _findate(self, timestamp):

        return FinDate(timestamp.day, timestamp.month, timestamp.year,
                       hh=timestamp.hour, mm=timestamp.minute, ss=timestamp.second)