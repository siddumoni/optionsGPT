# NSE equity-options charge model

## Purpose and scope

The paper broker estimates charges for a Zerodha NSE equity-option buy order
and sell order. It stores a per-side breakdown and uses the total in the cash
ledger and net P&L. The schedule is effective from **1 April 2026** and rejects
earlier trade dates until an earlier dated schedule is added.

This is a research estimate, not a broker contract note. Reconcile it against
Zerodha's actual contract notes before treating paper net P&L as exact.

## Current schedule

| Component | Rate / amount | Applied to |
|---|---:|---|
| Brokerage | ₹20 per executed option order | Each buy or sell order |
| NSE equity-options transaction charge incl. IPFT | 0.03553% | Premium turnover, each side |
| SEBI turnover fee | ₹10 per crore (0.0001%) | Premium turnover, each side |
| STT | 0.15% | Sell-side option premium |
| Stamp duty | 0.003% | Buy-side option premium |
| GST | 18% | Brokerage + exchange transaction charge + SEBI fee |

Premium turnover is option premium multiplied by quantity, not strike multiplied
by quantity.

Every component is rounded to paise using ROUND_HALF_UP. The paper broker
assumes one complete fill per side. Partial fills, order splitting, exercise,
physical settlement, expiry assignment and other exceptional levies are not
simulated by this schedule.

## Effective dates and source references

- Zerodha's published charges page lists flat ₹20 brokerage for option orders,
  NSE options transaction charges of 0.03553%, SEBI charges of ₹10/crore,
  GST of 18%, and stamp duty of 0.003% on the buy side:
  https://zerodha.com/charges/
- NSE Circular NSE/FA/73061 dated 27-Feb-2026 sets equity-options transaction
  charges at ₹3,552/crore plus ₹0.01/crore IPFT, totalling ₹3,553/crore,
  effective 1-Mar-2026:
  https://nsearchives.nseindia.com/content/circulars/FA73061.pdf
- NSE's STT page states option-sale STT of 0.15% effective 1-Apr-2026:
  https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax
- NSE's levies page lists SEBI turnover fees, stamp duty and GST:
  https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies

The schedule version is recorded on every paper entry/exit. When any published
rate changes, add a new effective-dated schedule and tests; do not edit an old
schedule in place because historical trade calculations must remain reproducible.

## Example

For one lot of 65 units bought at ₹100.10 and sold at ₹104.90:

- Entry premium turnover: ₹6,506.50; estimated entry charges: ₹26.54.
- Exit premium turnover: ₹6,818.50; estimated exit charges: ₹36.70.
- Gross P&L: ₹312.00.
- Estimated total charges: ₹63.24.
- Estimated net P&L: ₹248.76.

The example excludes any exercise/physical-settlement taxes and assumes the
paper fills at the displayed best ask on entry and best bid on exit.
