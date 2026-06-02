import unittest
from unittest.mock import Mock

from midi.engine3_sender import Engine3SysexSender


class Engine3SenderTest(unittest.TestCase):
    def test_send_messages_delegates_exact_messages(self):
        delegate = Mock()
        delegate.send_messages.return_value = 2
        messages = [bytes.fromhex("F0 42 30 F7"), bytes.fromhex("F0 42 31 F7")]
        progress = Mock()

        sent = Engine3SysexSender(delegate).send_messages(messages, 80, progress)

        self.assertEqual(sent, 2)
        delegate.send_messages.assert_called_once_with(messages, 80, progress)

    def test_cancel_before_send_returns_zero_and_resets(self):
        delegate = Mock()
        sender = Engine3SysexSender(delegate)

        sender.cancel()
        sent = sender.send_messages([bytes.fromhex("F0 42 30 F7")], 0)

        self.assertEqual(sent, 0)
        self.assertFalse(sender.cancel_requested)
        delegate.send_messages.assert_not_called()

    def test_cancel_forwards_to_delegate(self):
        delegate = Mock()

        Engine3SysexSender(delegate).cancel()

        delegate.cancel.assert_called_once()

    def test_cancelled_sender_can_be_reused_after_cancelled_call(self):
        delegate = Mock()
        delegate.send_messages.return_value = 1
        sender = Engine3SysexSender(delegate)

        sender.cancel()
        self.assertEqual(sender.send_messages([bytes.fromhex("F0 42 30 F7")], 0), 0)
        self.assertEqual(sender.send_messages([bytes.fromhex("F0 42 31 F7")], 0), 1)

        delegate.send_messages.assert_called_once()

    def test_invalid_sysex_raises_before_delegate_send(self):
        delegate = Mock()

        with self.assertRaises(ValueError):
            Engine3SysexSender(delegate).send_messages([bytes.fromhex("90 40 64")], 0)

        delegate.send_messages.assert_not_called()


if __name__ == "__main__":
    unittest.main()
