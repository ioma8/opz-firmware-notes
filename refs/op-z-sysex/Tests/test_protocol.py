import json
import unittest

from opzsysex.fileprotocol import DownloadState, PART_SIZE, SYNC_JOB_ID, UploadState, file_id
from opzsysex.midi_config import BYTE_COUNT, MIDIConfiguration
from opzsysex.project import GLOBAL_SIZE, PATTERN_BANK_SIZE, PATTERN_SIZE, GlobalEditor, Note, PatternBankEditor, decode_global
from opzsysex.serial import SerialMessage, decode_serial_frame, serial_frame
from opzsysex.sysex import MIDIStreamParser, ProtocolError, active_chain, decode_frame, frame, global_upload_frame, pack7, pattern_packet_identity, pattern_upload_frames, unpack7


class ProtocolTests(unittest.TestCase):
    def test_pack7_roundtrip_all_bytes(self):
        source = bytes(range(256))
        self.assertEqual(unpack7(pack7(source)), source)
        self.assertTrue(all(value < 128 for value in pack7(source)))

    def test_frame_roundtrip(self):
        source = bytes(range(32))
        self.assertEqual(decode_frame(frame(0x53, source)).payload, source)

    def test_realtime_inside_sysex(self):
        parser = MIDIStreamParser()
        target = frame(0x07, b"abc")
        events = parser.feed(target[:4] + b"\xF8" + target[4:])
        self.assertIn(("realtime", 0xF8), events)
        self.assertIn(("sysex", target), events)

    def test_serial_tunnel_roundtrip_and_known_ping(self):
        ping = serial_frame(0)
        self.assertEqual(ping, bytes((0xF0, 0x00, 0x20, 0x76, 0x01, 0x66, 0x01, 0x40, 0x05, 0, 0, 0, 0, 0, 0xF7)))
        source = SerialMessage(5, 1, b"\xC0\x7D")
        decoded = decode_serial_frame(serial_frame(source.message_type, source.payload, source.routing))
        self.assertEqual(decoded, source)

    def test_active_chain(self):
        decoded = decode_frame(active_chain([1, 2, 3], 4))
        self.assertEqual(decoded.message_id, 0x07)
        self.assertEqual(decoded.payload[:2], b"\x21\x03")
        self.assertEqual(decoded.payload[16:20], b"\x03\x01\x01\x04")

    def test_pattern_upload_roundtrip(self):
        bank = bytes((index * 17) & 0xFF for index in range(PATTERN_BANK_SIZE))
        frames = pattern_upload_frames(bank, 0x2F, 0x1234)
        compressed = bytearray()
        for index, item in enumerate(frames):
            decoded = decode_frame(item)
            self.assertEqual(decoded.message_id, 0x0A if index == len(frames) - 1 else 0x09)
            self.assertEqual(pattern_packet_identity(item), (0x1234, index))
            compressed.extend(decoded.payload[6:])
        import zlib
        self.assertEqual(zlib.decompress(compressed), bank)

    def test_global_edit_preserves_unrelated_bytes(self):
        source = bytes((index * 3) & 0xFF for index in range(GLOBAL_SIZE))
        editor = GlobalEditor(source)
        editor.set_tempo(123)
        editor.set_chain(2, [1, 5, 9])
        changed = editor.bytes()
        self.assertEqual(changed[516:518], b"{\x00")
        self.assertEqual(changed[64:68], b"\x01\x05\x09\xFF")
        self.assertEqual(decode_global(changed).tempo, 123)
        self.assertEqual(decode_frame(global_upload_frame(changed)).message_id, 0x0C)

    def test_pattern_notes_and_lock_touch_only_expected_bytes(self):
        source = bytearray(PATTERN_BANK_SIZE)
        for pattern in range(16):
            for step in range(16):
                for slot in range(55):
                    source[pattern * PATTERN_SIZE + 192 + (step * 55 + slot) * 8 + 4] = 0xFF
        editor = PatternBankEditor(bytes(source))
        editor.set_notes(3, 6, 4, [Note(60, 91, 6200, -1), Note(67, 92, 12400, 2)])
        editor.set_parameter_lock(3, 6, 4, 8, 201)
        changed = editor.bytes()
        first = 3 * PATTERN_SIZE + 192 + (4 * 55 + 16) * 8
        self.assertEqual(changed[first + 4:first + 7], bytes((60, 91, 0xF8)))
        step_offset = 3 * PATTERN_SIZE + 7_232 + (6 * 16 + 4) * 54
        self.assertEqual(changed[step_offset + 26], 201)
        self.assertEqual(changed[step_offset + 44], 0xFF)

    def test_midi_configuration_roundtrip(self):
        raw = bytearray(BYTE_COUNT)
        raw[289:292] = b"\x11\x22\x33"
        config = MIDIConfiguration.decode(bytes(raw))
        config.set_track_enabled(5, True)
        config.set_channel(5, 12)
        config.set_cc(5, 3, 74)
        config.set_setting(3, True)
        self.assertEqual(MIDIConfiguration.decode_frame(config.write_frame()).encode(), config.encode())

    def test_file_id_and_manifest(self):
        self.assertEqual(file_id("settings/slotConfiguration.json"), 2_873_598_156)
        state = UploadState([("samplepacks/test.aif", b"synthetic")], [1234])
        manifest = json.loads(state.sync_job)
        self.assertEqual(manifest["files"][0]["path"], "samplepacks/test.aif")
        self.assertEqual(manifest["files"][1], {"operation": "remove", "plugId": 1234})

    def test_file_upload_download_parts(self):
        content = bytes(range(256))
        upload = UploadState([("example.bin", content)])
        identifier = upload.descriptors[0].file_id
        upload.accept_request((0x2222).to_bytes(2, "little") + identifier.to_bytes(4, "little") + b"\0\0", 0x2222)
        first = decode_frame(upload.next_frame(0x1111, now=0)).payload
        self.assertEqual(first[8], 0)
        upload.accept_request((0x2222).to_bytes(2, "little") + identifier.to_bytes(4, "little") + b"\1\0", 0x2222)
        second = decode_frame(upload.next_frame(0x1111, now=1)).payload
        self.assertEqual(second[8], 1)
        download = DownloadState([(identifier, "example.bin")])
        self.assertIsNotNone(download.begin(0x1111))
        completed, request = download.accept_part((0x2222).to_bytes(2, "little") + first[2:], 0x2222, 0x1111)
        self.assertIsNone(completed)
        self.assertIsNotNone(request)
        completed, request = download.accept_part((0x2222).to_bytes(2, "little") + second[2:], 0x2222, 0x1111)
        self.assertEqual(completed, ("example.bin", content))
        self.assertIsNone(request)

    def test_validation_fails_closed(self):
        with self.assertRaises(ProtocolError):
            PatternBankEditor(b"short")
        with self.assertRaises(ProtocolError):
            GlobalEditor(bytes(GLOBAL_SIZE)).set_tempo(300)
        with self.assertRaises(ProtocolError):
            serial_frame(0x30)
        with self.assertRaises(ProtocolError):
            UploadState([("empty.bin", b"")])


if __name__ == "__main__":
    unittest.main()
