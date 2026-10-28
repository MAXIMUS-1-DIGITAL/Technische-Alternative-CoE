"""CoE state observer to track state changes."""

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from ta_cmi import ApiError, CoE

RESEND_DELAY = 5

from .const import (
    ANALOG_DOMAINS,
    CONF_ANALOG_ENTITIES,
    CONF_DIGITAL_ENTITIES,
    DIGITAL_DOMAINS,
    TYPE_BINARY,
    TYPE_SENSOR,
    _LOGGER,
    ConfEntityToSend,
)
from .state_sender import StateSender


class StateObserver:
    """Handle state updates for configured entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        coe: CoE,
        sender: StateSender,
        entity_config: dict[str, list[ConfEntityToSend]],
    ):
        """Initialize."""
        self._hass = hass
        self._coe = coe
        self._sender = sender
        self._entity_dict = entity_config
        self._entity_list = [
            x.entity_id
            for x in entity_config.get(CONF_ANALOG_ENTITIES, [])
            + entity_config.get(CONF_DIGITAL_ENTITIES, [])
        ]

        self._states = {TYPE_BINARY: {}, TYPE_SENSOR: {}}
        self._cancel_resend: CALLBACK_TYPE | None = None

        self._unsubscribe = async_track_state_change_event(
            self._hass, self._entity_list, self._update_listener
        )

    def unload(self) -> None:
        """Remove the state change listener and a pending resend."""
        self._unsubscribe()
        if self._cancel_resend is not None:
            self._cancel_resend()
            self._cancel_resend = None

    @callback
    def _schedule_resend(self, err: ApiError) -> None:
        """Resend all values once after a short delay."""
        _LOGGER.warning(
            "Sending to the CoE server failed, resend in %s s: %s", RESEND_DELAY, err
        )
        if self._cancel_resend is not None:
            return
        self._cancel_resend = async_call_later(self._hass, RESEND_DELAY, self._resend)

    async def _resend(self, _now) -> None:
        """Send all values after a failed send."""
        self._cancel_resend = None
        try:
            await self._sender.update()
        except ApiError as err:
            _LOGGER.warning(
                "Resend to the CoE server failed, next try with the periodic refresh: %s",
                err,
            )

    @staticmethod
    def _is_state_valid(state: str) -> bool:
        """Check if a state is valid."""
        return state not in ["unavailable", "unknown"]

    def _has_state_changed(self, state: State) -> bool:
        """Check if a state is new."""
        return (
            self._states[TYPE_BINARY].get(state.entity_id) != state.state
            and self._states[TYPE_SENSOR].get(state.entity_id) != state.state
        )

    async def get_all_states(self) -> None:
        """Get all states from entities."""
        _LOGGER.debug("Update all states")

        for entity_id in self._entity_list:

            state = self._hass.states.get(entity_id)
            domain = entity_id[0 : entity_id.find(".")]

            if state is None or not self._is_state_valid(state.state):
                continue

            if domain in ANALOG_DOMAINS:
                state_value = float(state.state)
                self._states[TYPE_SENSOR][entity_id] = state_value
                self._sender.update_analog_manuel(
                    entity_id,
                    state_value,
                    str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")),
                )

            if domain in DIGITAL_DOMAINS:
                state_value = state.state is STATE_ON
                self._states[TYPE_BINARY][entity_id] = state_value
                self._sender.update_digital_manuel(entity_id, state_value)

        try:
            await self._sender.update()
        except ApiError as err:
            self._schedule_resend(err)

    @callback
    async def _update_listener(self, event: Event) -> None:
        """Handle state updates."""
        new_state: State | None = event.data.get("new_state", None)

        if (
            new_state is None
            or not self._is_state_valid(new_state.state)
            or not self._has_state_changed(new_state)
        ):
            return

        _LOGGER.debug(f"Handle new state {new_state.entity_id}: {new_state.state}")

        try:
            if new_state.domain in ANALOG_DOMAINS:
                state_value = float(new_state.state)

                self._states[TYPE_SENSOR][new_state.entity_id] = state_value

                await self._sender.update_analog(
                    new_state.entity_id,
                    state_value,
                    str(new_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")),
                )

            if new_state.domain in DIGITAL_DOMAINS:
                state_value = new_state.state is STATE_ON
                self._states[TYPE_BINARY][new_state.entity_id] = state_value

                await self._sender.update_digital(new_state.entity_id, state_value)
        except ApiError as err:
            self._schedule_resend(err)
