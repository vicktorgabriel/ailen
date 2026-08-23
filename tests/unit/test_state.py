"""Unit tests for assistant interaction state transitions."""

import unittest

from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState


class TestState(unittest.TestCase):
    """Test suite for state machine transitions."""

    def test_valid_transitions(self):
        sm = StateManager(AssistantState.BOOTING)
        self.assertEqual(sm.current_state, AssistantState.BOOTING)

        # BOOTING -> IDLE
        self.assertTrue(sm.transition_to(AssistantState.IDLE, reason="boot complete"))
        self.assertEqual(sm.current_state, AssistantState.IDLE)

        # IDLE -> ATTENTION
        self.assertTrue(sm.transition_to(AssistantState.ATTENTION, reason="face detected"))
        self.assertEqual(sm.current_state, AssistantState.ATTENTION)

        # ATTENTION -> LISTENING
        self.assertTrue(sm.transition_to(AssistantState.LISTENING, reason="wake word"))
        self.assertEqual(sm.current_state, AssistantState.LISTENING)

        # LISTENING -> PROCESSING
        self.assertTrue(sm.transition_to(AssistantState.PROCESSING, reason="speech done"))
        self.assertEqual(sm.current_state, AssistantState.PROCESSING)

        # PROCESSING -> SPEAKING
        self.assertTrue(sm.transition_to(AssistantState.SPEAKING, reason="tts ready"))
        self.assertEqual(sm.current_state, AssistantState.SPEAKING)

        # SPEAKING -> IDLE
        self.assertTrue(sm.transition_to(AssistantState.IDLE, reason="speaking finished"))
        self.assertEqual(sm.current_state, AssistantState.IDLE)

    def test_invalid_transition(self):
        sm = StateManager(AssistantState.BOOTING)
        # Cannot go directly from BOOTING to SPEAKING
        self.assertFalse(sm.transition_to(AssistantState.SPEAKING, reason="invalid leap"))
        self.assertEqual(sm.current_state, AssistantState.BOOTING)

    def test_processing_to_attention_allowed_after_conversation(self):
        sm = StateManager(AssistantState.ATTENTION)
        self.assertTrue(sm.transition_to(AssistantState.PROCESSING, reason="ai_processing"))
        self.assertTrue(sm.transition_to(AssistantState.ATTENTION, reason="conversation_complete"))
        self.assertEqual(sm.current_state, AssistantState.ATTENTION)

    def test_processing_to_listening_race_is_rejected(self):
        sm = StateManager(AssistantState.LISTENING)
        self.assertTrue(sm.transition_to(AssistantState.PROCESSING, reason="ai_processing"))
        # A new transcript arriving while still PROCESSING must never flip to LISTENING.
        self.assertFalse(sm.transition_to(AssistantState.LISTENING, reason="race"))
        self.assertEqual(sm.current_state, AssistantState.PROCESSING)

    def test_listener_callback(self):
        sm = StateManager(AssistantState.BOOTING)
        changes = []

        def on_change(old_s: AssistantState, new_s: AssistantState):
            changes.append((old_s, new_s))

        sm.add_listener(on_change)
        sm.transition_to(AssistantState.IDLE)

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0], (AssistantState.BOOTING, AssistantState.IDLE))


if __name__ == "__main__":
    unittest.main()
