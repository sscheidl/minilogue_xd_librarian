"""Local slot model for minilogue xd logue SDK user units."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserUnitSlotDefinition:
    key: str
    label: str
    kind: str
    accepts_modules: tuple[str, ...]


USER_OSC_SLOTS = tuple(
    UserUnitSlotDefinition(
        key=f"osc-{index:02d}",
        label=f"User OSC {index:02d}",
        kind="user-osc",
        accepts_modules=("osc",),
    )
    for index in range(1, 17)
)

USER_FX_SLOTS = tuple(
    [
        *(
            UserUnitSlotDefinition(
                key=f"modfx-{index:02d}",
                label=f"Mod FX {index:02d}",
                kind="user-fx",
                accepts_modules=("modfx",),
            )
            for index in range(1, 17)
        ),
        *(
            UserUnitSlotDefinition(
                key=f"delfx-{index:02d}",
                label=f"Delay FX {index:02d}",
                kind="user-fx",
                accepts_modules=("delfx",),
            )
            for index in range(1, 9)
        ),
        *(
            UserUnitSlotDefinition(
                key=f"revfx-{index:02d}",
                label=f"Reverb FX {index:02d}",
                kind="user-fx",
                accepts_modules=("revfx",),
            )
            for index in range(1, 9)
        ),
    ]
)

USER_UNIT_SLOTS = USER_OSC_SLOTS + USER_FX_SLOTS
USER_UNIT_SLOTS_BY_KEY = {slot.key: slot for slot in USER_UNIT_SLOTS}


def matching_slots(module: str) -> tuple[UserUnitSlotDefinition, ...]:
    return tuple(slot for slot in USER_UNIT_SLOTS if module in slot.accepts_modules)
