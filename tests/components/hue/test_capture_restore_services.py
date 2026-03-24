"""Tests for Hue capture_group_scene and restore_group_scene services."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from homeassistant.components.hue.const import (
    ATTR_GROUPS,
    ATTR_SCENE_BRIGHTNESS,
    ATTR_SCENE_ENTITY_ID,
    ATTR_SCENE_MODE,
    ATTR_SCENE_SPEED,
    ATTR_SMART_SCENE_ENTITY_ID,
    DOMAIN,
)
from homeassistant.components.hue.services import (
    async_setup_services,
    restore_group_scene,
)
from homeassistant.components.hue.v2.scene_activity import (
    get_or_create_scene_activity_manager,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.json import JsonArrayType

from .conftest import setup_platform


async def _setup(
    hass: HomeAssistant,
    mock_bridge_v2: Mock,
    v2_resources_test_data: JsonArrayType,
) -> None:
    """Set up hue V2 bridge with light, scene, and select platforms + services."""
    await mock_bridge_v2.api.load_test_data(v2_resources_test_data)
    await setup_platform(
        hass, mock_bridge_v2, [Platform.LIGHT, Platform.SCENE, Platform.SELECT]
    )
    # setup_platform skips async_setup, so register services explicitly
    async_setup_services(hass)

    # The scene activity manager may have been created before scene entities
    # were registered. Re-process scenes so entity_ids are resolved.
    manager = get_or_create_scene_activity_manager(hass, mock_bridge_v2.api)
    for scene in mock_bridge_v2.api.scenes.scene:
        manager._apply_scene_update(scene)
    for smart_scene in mock_bridge_v2.api.scenes.smart_scene:
        manager._apply_scene_update(smart_scene)


async def test_capture_regular_scene(
    hass: HomeAssistant, mock_bridge_v2: Mock, v2_resources_test_data: JsonArrayType
) -> None:
    """Test capturing a regular active scene for a grouped light."""
    await _setup(hass, mock_bridge_v2, v2_resources_test_data)

    # "Test Room" grouped light should exist with is_hue_group attribute
    room_light = hass.states.get("light.test_room")
    assert room_light is not None
    assert room_light.attributes.get("is_hue_group") is True

    result = await hass.services.async_call(
        DOMAIN,
        "capture_group_scene",
        {"entity_id": ["light.test_room"]},
        blocking=True,
        return_response=True,
    )

    assert ATTR_GROUPS in result
    groups = result[ATTR_GROUPS]
    assert "light.test_room" in groups

    scene_state = groups["light.test_room"]
    # Regular Test Scene is active (static) in fixture
    assert ATTR_SCENE_ENTITY_ID in scene_state
    assert scene_state[ATTR_SCENE_MODE] == "static"


async def test_capture_dynamic_scene(
    hass: HomeAssistant, mock_bridge_v2: Mock, v2_resources_test_data: JsonArrayType
) -> None:
    """Test capturing a dynamic scene includes speed and brightness."""
    await _setup(hass, mock_bridge_v2, v2_resources_test_data)

    # "Test Zone" has a dynamic_palette scene active
    zone_light = hass.states.get("light.test_zone")
    assert zone_light is not None
    assert zone_light.attributes.get("is_hue_group") is True

    result = await hass.services.async_call(
        DOMAIN,
        "capture_group_scene",
        {"entity_id": ["light.test_zone"]},
        blocking=True,
        return_response=True,
    )

    groups = result[ATTR_GROUPS]
    assert "light.test_zone" in groups

    scene_state = groups["light.test_zone"]
    assert scene_state[ATTR_SCENE_MODE] == "dynamic_palette"
    assert ATTR_SCENE_SPEED in scene_state
    assert ATTR_SCENE_BRIGHTNESS in scene_state


async def test_capture_smart_scene(
    hass: HomeAssistant, mock_bridge_v2: Mock, v2_resources_test_data: JsonArrayType
) -> None:
    """Test capturing a smart scene for a grouped light."""
    await _setup(hass, mock_bridge_v2, v2_resources_test_data)

    result = await hass.services.async_call(
        DOMAIN,
        "capture_group_scene",
        {"entity_id": ["light.test_room"]},
        blocking=True,
        return_response=True,
    )

    groups = result[ATTR_GROUPS]
    scene_state = groups["light.test_room"]
    # Test Room has a smart scene active in fixture
    assert ATTR_SMART_SCENE_ENTITY_ID in scene_state


async def test_capture_no_active_scene(
    hass: HomeAssistant, mock_bridge_v2: Mock, v2_resources_test_data: JsonArrayType
) -> None:
    """Test capture returns empty groups when no scene is active."""
    await _setup(hass, mock_bridge_v2, v2_resources_test_data)

    # Deactivate all scenes for the room
    room_scene_id = "cdbf3740-7977-4a11-8275-8c78636ad4bd"
    smart_scene_id = "8abe5a3e-94c8-4058-908f-56241818509a"

    mock_bridge_v2.api.emit_event(
        "update",
        {
            "id": room_scene_id,
            "type": "scene",
            "status": {"active": "inactive"},
        },
    )
    mock_bridge_v2.api.emit_event(
        "update",
        {"id": smart_scene_id, "type": "smart_scene", "state": "inactive"},
    )
    await hass.async_block_till_done()

    result = await hass.services.async_call(
        DOMAIN,
        "capture_group_scene",
        {"entity_id": ["light.test_room"]},
        blocking=True,
        return_response=True,
    )

    groups = result[ATTR_GROUPS]
    assert "light.test_room" not in groups


async def test_capture_non_hue_entity(
    hass: HomeAssistant, mock_bridge_v2: Mock, v2_resources_test_data: JsonArrayType
) -> None:
    """Test capture ignores entities that are not Hue grouped lights."""
    await _setup(hass, mock_bridge_v2, v2_resources_test_data)

    result = await hass.services.async_call(
        DOMAIN,
        "capture_group_scene",
        {"entity_id": ["light.nonexistent"]},
        blocking=True,
        return_response=True,
    )

    assert result[ATTR_GROUPS] == {}


async def test_capture_multiple_entities(
    hass: HomeAssistant, mock_bridge_v2: Mock, v2_resources_test_data: JsonArrayType
) -> None:
    """Test capturing multiple grouped lights at once."""
    await _setup(hass, mock_bridge_v2, v2_resources_test_data)

    result = await hass.services.async_call(
        DOMAIN,
        "capture_group_scene",
        {"entity_id": ["light.test_room", "light.test_zone"]},
        blocking=True,
        return_response=True,
    )

    groups = result[ATTR_GROUPS]
    assert "light.test_room" in groups
    assert "light.test_zone" in groups

    # Room has static regular + active smart scene
    room_state = groups["light.test_room"]
    assert room_state[ATTR_SCENE_MODE] == "static"
    assert ATTR_SMART_SCENE_ENTITY_ID in room_state

    # Zone has dynamic_palette regular scene
    zone_state = groups["light.test_zone"]
    assert zone_state[ATTR_SCENE_MODE] == "dynamic_palette"


async def test_restore_regular_scene(
    hass: HomeAssistant, mock_bridge_v2: Mock, v2_resources_test_data: JsonArrayType
) -> None:
    """Test restoring a captured regular scene triggers scene recall."""
    await _setup(hass, mock_bridge_v2, v2_resources_test_data)

    # Capture
    result = await hass.services.async_call(
        DOMAIN,
        "capture_group_scene",
        {"entity_id": ["light.test_room"]},
        blocking=True,
        return_response=True,
    )

    # Clear mock requests to isolate restore calls
    mock_bridge_v2.mock_requests.clear()

    # Restore
    await hass.services.async_call(
        DOMAIN,
        "restore_group_scene",
        {ATTR_GROUPS: result[ATTR_GROUPS]},
        blocking=True,
    )

    # The restore should have triggered a scene recall via the bridge API
    assert len(mock_bridge_v2.mock_requests) > 0


async def test_restore_empty_groups_raises(
    hass: HomeAssistant,
) -> None:
    """Test restoring with empty groups raises ServiceValidationError."""
    mock_call = Mock()
    mock_call.hass = hass
    mock_call.data = {ATTR_GROUPS: {}}

    with pytest.raises(ServiceValidationError, match="no_scene_to_restore"):
        await restore_group_scene(mock_call)


async def test_restore_dynamic_scene(
    hass: HomeAssistant, mock_bridge_v2: Mock, v2_resources_test_data: JsonArrayType
) -> None:
    """Test restoring a dynamic_palette scene includes speed and brightness."""
    await _setup(hass, mock_bridge_v2, v2_resources_test_data)

    # Capture the zone which has a dynamic_palette scene
    result = await hass.services.async_call(
        DOMAIN,
        "capture_group_scene",
        {"entity_id": ["light.test_zone"]},
        blocking=True,
        return_response=True,
    )

    groups = result[ATTR_GROUPS]
    assert groups["light.test_zone"][ATTR_SCENE_MODE] == "dynamic_palette"

    # Clear and restore
    mock_bridge_v2.mock_requests.clear()

    await hass.services.async_call(
        DOMAIN,
        "restore_group_scene",
        {ATTR_GROUPS: groups},
        blocking=True,
    )

    # Should have recalled the scene
    assert len(mock_bridge_v2.mock_requests) > 0


async def test_restore_roundtrip(
    hass: HomeAssistant, mock_bridge_v2: Mock, v2_resources_test_data: JsonArrayType
) -> None:
    """Test full capture and restore roundtrip for multiple entities."""
    await _setup(hass, mock_bridge_v2, v2_resources_test_data)

    # Capture both room and zone
    result = await hass.services.async_call(
        DOMAIN,
        "capture_group_scene",
        {"entity_id": ["light.test_room", "light.test_zone"]},
        blocking=True,
        return_response=True,
    )

    mock_bridge_v2.mock_requests.clear()

    # Restore all
    await hass.services.async_call(
        DOMAIN,
        "restore_group_scene",
        {ATTR_GROUPS: result[ATTR_GROUPS]},
        blocking=True,
    )

    # Should have recalled scenes for both groups
    assert len(mock_bridge_v2.mock_requests) >= 2
