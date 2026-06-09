"""Safe destination-aware validation for local User Unit assignment."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from devices.korg_minilogue_xd.unit_container import UnitContainerData, load_unit_container
from devices.korg_minilogue_xd.unit_manifest import ManifestInfo, parse_manifest_info
from devices.korg_minilogue_xd.unit_payload import detect_payload_module
from devices.korg_minilogue_xd.unit_types import (
    API_1_1_MIN_FIRMWARE,
    SUPPORTED_API_MAX,
    SUPPORTED_XD_PLATFORMS,
    UnitModule,
    VersionTriple,
    parse_firmware_version,
    slot_key_for,
    validate_slot_index,
)


@dataclass(frozen=True)
class ValidatedUserUnit:
    source_path: Path
    platform: str
    module: UnitModule
    api_version: VersionTriple
    unit_version: VersionTriple
    display_name: str
    developer_id: int | None
    program_id: int | None
    payload_magic: bytes
    payload_size: int
    payload_crc32: int
    payload_bytes: bytes
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class UnitValidationResult:
    ok: bool
    unit: ValidatedUserUnit | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    user_message: str


class UserUnitValidator:
    """Validate a local unit file for a specific target module and slot."""

    def validate_for_destination(
        self,
        *,
        path: Path,
        destination_module: UnitModule,
        destination_slot: int,
        installed_firmware: str | None = None,
    ) -> UnitValidationResult:
        if not validate_slot_index(destination_module, destination_slot):
            return self._failure(
                "Invalid destination slot.",
                f"The selected destination slot {destination_slot + 1:02d} is outside the valid range for {destination_module.tab_display_name}.",
            )

        try:
            container = load_unit_container(path)
        except ValueError as exc:
            return self._failure(str(exc), str(exc))

        manifest_info = parse_manifest_info(container.header, path.stem)
        return self._validate_loaded(
            container=container,
            manifest_info=manifest_info,
            destination_module=destination_module,
            destination_slot=destination_slot,
            installed_firmware=installed_firmware,
        )

    def restage_unit(
        self,
        unit: ValidatedUserUnit,
        *,
        new_source_path: Path,
    ) -> ValidatedUserUnit:
        return replace(unit, source_path=new_source_path)

    def _validate_loaded(
        self,
        *,
        container: UnitContainerData,
        manifest_info: ManifestInfo,
        destination_module: UnitModule,
        destination_slot: int,
        installed_firmware: str | None,
    ) -> UnitValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        payload_module = detect_payload_module(container.payload_magic)

        platform = manifest_info.platform.strip().lower().replace("_", "-")
        if platform not in SUPPORTED_XD_PLATFORMS:
            errors.append(
                f"This unit targets '{manifest_info.platform or 'unknown'}', not minilogue xd."
            )

        if manifest_info.module is None:
            errors.append("The unit manifest contains an unknown module type.")
        if payload_module is None:
            errors.append(
                f"Unknown payload magic '{container.payload_magic.decode('ascii', errors='replace') or 'empty'}'."
            )
        if manifest_info.module is not None and payload_module is not None and manifest_info.module != payload_module:
            errors.append(
                "Manifest module and payload magic do not describe the same unit type."
            )
        detected_module = payload_module or manifest_info.module
        if detected_module is not None and detected_module != destination_module:
            errors.append(self._destination_mismatch_message(
                display_name=manifest_info.display_name,
                detected_module=detected_module,
                destination_module=destination_module,
                destination_slot=destination_slot,
            ))

        if manifest_info.api_version is None:
            errors.append("The unit API version is missing or invalid.")
        elif manifest_info.api_version.major != SUPPORTED_API_MAX.major:
            errors.append(f"Unsupported API major version {manifest_info.api_version.major}.")
        elif manifest_info.api_version.minor > SUPPORTED_API_MAX.minor:
            errors.append(f"Unsupported API minor version {manifest_info.api_version}.")
        elif manifest_info.api_version.minor == 1:
            firmware_version = parse_firmware_version(installed_firmware or "")
            if firmware_version is None:
                warnings.append("API 1.1 units may require minilogue xd firmware 2.00 or newer.")
            elif firmware_version < API_1_1_MIN_FIRMWARE:
                errors.append(
                    f"API {manifest_info.api_version} requires minilogue xd firmware 2.00 or newer."
                )

        if manifest_info.unit_version is None:
            errors.append("The unit version is missing or invalid.")

        if manifest_info.module == UnitModule.OSC:
            if manifest_info.num_param > 6:
                errors.append("User Oscillator units may define at most 6 parameters.")
            if len(manifest_info.params) != manifest_info.num_param:
                errors.append("OSC parameter list length does not match num_param.")
        elif manifest_info.module in {UnitModule.MOD_FX, UnitModule.DELAY_FX, UnitModule.REVERB_FX}:
            if manifest_info.num_param != 0:
                warnings.append("FX units normally declare num_param = 0.")

        if errors:
            user_message = errors[0]
            if len(errors) > 1:
                user_message += "\n\n" + "\n".join(f"- {item}" for item in errors[1:])
            user_message += "\n\nNo assignment was changed."
            return UnitValidationResult(
                ok=False,
                unit=None,
                errors=tuple(errors),
                warnings=tuple(warnings),
                user_message=user_message,
            )

        assert detected_module is not None
        assert manifest_info.api_version is not None
        assert manifest_info.unit_version is not None
        unit = ValidatedUserUnit(
            source_path=container.source_path,
            platform=manifest_info.platform,
            module=detected_module,
            api_version=manifest_info.api_version,
            unit_version=manifest_info.unit_version,
            display_name=manifest_info.display_name,
            developer_id=manifest_info.developer_id,
            program_id=manifest_info.program_id,
            payload_magic=container.payload_magic,
            payload_size=container.payload_size,
            payload_crc32=container.payload_crc32,
            payload_bytes=container.payload_bytes,
            warnings=tuple(warnings),
        )
        return UnitValidationResult(
            ok=True,
            unit=unit,
            errors=(),
            warnings=tuple(warnings),
            user_message="OK",
        )

    @staticmethod
    def _failure(error: str, user_message: str) -> UnitValidationResult:
        return UnitValidationResult(
            ok=False,
            unit=None,
            errors=(error,),
            warnings=(),
            user_message=user_message + "\n\nNo assignment was changed.",
        )

    @staticmethod
    def _destination_mismatch_message(
        *,
        display_name: str,
        detected_module: UnitModule,
        destination_module: UnitModule,
        destination_slot: int,
    ) -> str:
        return (
            f"Cannot load '{display_name}' into {destination_module.tab_display_name} slot {destination_slot + 1:02d}.\n\n"
            f"Detected unit type: {detected_module.display_name}\n"
            f"Selected destination: {destination_module.tab_display_name} slot {destination_slot + 1:02d}\n"
            f"Allowed destination: {detected_module.slot_range_text}"
        )
