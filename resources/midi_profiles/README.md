MIDI profile JSON files for the MIDI Monitor.

Expected top-level fields:

- `profile_id`: stable internal id
- `display_name`: user-facing name in the profile picker
- `manufacturer`
- `device`
- `midi_channel_base`
- `notes`
- `event_names`: optional display labels for message types like `note_on`
- `control_changes`: CC definitions keyed by CC number
- `special_controls`: helper/control definitions keyed by CC number

Supported control fields:

- `name`
- `group`
- `type`: `continuous`, `selection`, `switch`, or `helper`
- `min`
- `max`
- `notes`
- `show_in_simple_view`
- `show_in_technical_view`
- `value_map`

Supported `value_map` entries:

- `{ "value": 64, "label": "Triangle" }`
- `{ "range": [64, 127], "label": "On" }`

Unknown fields are ignored so profiles remain easy to extend by hand.
