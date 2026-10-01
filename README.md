# Vehicle Logbook for Home Assistant

A logbook for your vehicles inside Home Assistant: fuel, services, oil, tyres, parts, paperwork and running costs, with reminders before things fall due.

Everything is stored locally in Home Assistant. Nothing is sent anywhere.

## Features

- **One device per vehicle**, added from *Settings → Devices & services*.
- **Fuel:** full-tank-to-full-tank consumption (L/100 km), fuel cost per km, last price per litre and monthly fuel spend.
- **Services and oil:** the next service is due by km *or* date, whichever comes first. If the workshop gives you its own next-service km or date, that is used instead.
- **Tyres:** rotation due, km on the current set, tyre age from the DOT date, and a replacement warning at 1.6 mm tread.
- **Parts:** battery, brake pads, discs, brake fluid, wiper blades, filters, coolant, spark plugs, timing belt, shocks, clutch and more. Each part has a default interval that you can override when you log it.
- **Paperwork:** licence disc, insurance, roadworthy, warranty, service plan and tracker expiry.
- **Costs:** this month, this year (by category), total, and running cost per km.
- **Reminders:**
  - Each tracked item has a status: OK / Due soon / Overdue.
  - A *Needs attention* binary sensor is on when anything is due soon or overdue.
  - A *Next due* sensor shows what falls due first.
- **Calendar:** upcoming due dates plus your workshop history. Due dates for km-based items are estimated from how much you drive.
- **Linked odometer:** point it at any odometer sensor (for example FordPass) and readings update automatically.
- **Fuelio import:** import a Fuelio CSV export. Re-importing skips records you already have. Obvious typos, such as 925 L instead of 92.5 L or a zero price, are flagged and left out of the stats.

## Installation (HACS)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gcp-glitch&repository=ha-vehicle-logbook&category=integration)

1. Click the button above, or in HACS go to *⋮ → Custom repositories*, add `https://github.com/gcp-glitch/ha-vehicle-logbook` and choose the type **Integration**.
2. Download **Vehicle Logbook** and restart Home Assistant.
3. Add your first vehicle with the button below, or go to *Settings → Devices & services → Add integration → Vehicle Logbook*. Add one entry per vehicle.

[![Open your Home Assistant instance and start setting up Vehicle Logbook.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=vehicle_logbook)

## Actions

| Action | What it does |
|---|---|
| `vehicle_logbook.log_fillup` | Fuel fill-up. Give the total cost or the price per litre. |
| `vehicle_logbook.log_service` | Workshop service, optionally with the workshop's next-service km or date. |
| `vehicle_logbook.log_oil_change` | Oil change outside a service. |
| `vehicle_logbook.log_tyres` | New tyres, rotation, repair or tread check. |
| `vehicle_logbook.log_part` | Replaced part, with an optional custom interval. |
| `vehicle_logbook.set_document` | Licence disc, insurance or other document expiry. |
| `vehicle_logbook.log_expense` | Any other cost: tolls, parking, wash, finance and so on. |
| `vehicle_logbook.set_odometer` | Manual odometer reading. |
| `vehicle_logbook.update_record` / `delete_record` | Fix or remove a record. |
| `vehicle_logbook.import_fuelio_csv` | Import a Fuelio export, from a file path under `/config` or pasted CSV text. |
| `vehicle_logbook.get_records` | Return records, newest first, for scripts and dashboards. |

When the vehicle has a linked odometer sensor, `odometer` is optional everywhere.

```yaml
action: vehicle_logbook.log_fillup
data:
  vehicle: <config entry id>   # pick the vehicle in the UI
  litres: 72.4
  total_cost: 2331.28
```

## Example automation

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.ford_ranger_needs_attention
    to: "on"
actions:
  - action: notify.mobile_app_phone
    data:
      title: "🔧 Ford Ranger"
      message: >-
        {{ state_attr('binary_sensor.ford_ranger_needs_attention', 'items')
           | map(attribute='item') | join(', ') }} due soon.
```

## Development

```bash
pip install -r requirements_test.txt
pytest
```

## License

MIT
