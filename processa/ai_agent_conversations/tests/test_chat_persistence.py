import json

import frappe
from frappe.tests.utils import FrappeTestCase
from processa.ai_agent_conversations.chat_persistence import (
    create_conversation,
    close_conversation,
    save_user_message,
    save_bot_message,
    load_history,
    get_or_create_state,
    update_state
)

class TestChatPersistence(FrappeTestCase):
    def test_cache_chat_lifecycle(self):
        # 1. Create conversation
        conv_name = create_conversation(
            agent_mode="ProsAlly",
            title="Test Chat",
            user="Administrator"
        )
        self.assertTrue(frappe.db.exists("Chat Conversation", conv_name))
        
        # 2. Save user and bot messages
        msg1 = save_user_message(conv_name, "Hello assistant")
        msg2 = save_bot_message(conv_name, "Hello human", metadata={"intent": "GREET"})
        
        self.assertTrue(frappe.db.exists("Chat Message", msg1))
        self.assertTrue(frappe.db.exists("Chat Message", msg2))
        
        # 3. Load history
        history = load_history(conv_name, limit=5)
        self.assertEqual(len(history), 2)
        # Compared field by field rather than as whole dicts: load_history now
        # returns the Chat Message name and its creation timestamp
        # alongside role and content. A strict equality would fail on
        # those and invite someone to "fix" it by deleting them.
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "Hello assistant")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertEqual(history[1]["content"], "Hello human")
        # The row id, so a redrawn reply can still be rated
        self.assertEqual(history[0]["message"], msg1)
        self.assertEqual(history[1]["message"], msg2)
        # Every history row carries the message's creation timestamp
        for row in history:
            self.assertTrue(row["timestamp"])
        
        # 4. State management
        state = get_or_create_state(conv_name, initial_data={"step": "start"})
        self.assertEqual(state, {"step": "start"})
        
        update_state(conv_name, {"step": "step2"})
        state2 = get_or_create_state(conv_name)
        self.assertEqual(state2, {"step": "step2"})
        
        # 5. The conversation and its two messages are stored as documents
        self.assertTrue(frappe.db.exists("Chat Conversation", conv_name))
        self.assertEqual(frappe.db.count("Chat Message", {"conversation": conv_name}), 2)

    def test_conversation_title_from_pasted_xml_fits_the_column(self):
        xml = (
            '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_1" '
            'targetNamespace="http://example.com"><bpmn:process id="P1" isExecutable="true">'
            '<bpmn:startEvent id="S1" name="Request received"/></bpmn:process></bpmn:definitions>'
        )
        name = create_conversation(agent_mode="ProsAlly", title=xml, user="Administrator", commit=False)
        self.assertEqual(frappe.db.get_value("Chat Conversation", name, "title"), "New chat")

    def test_conversation_title_keeps_the_text_of_a_mixed_message(self):
        name = create_conversation(
            agent_mode="ProsAlly", title="check this <bpmn:task id=\"T1\"/>", user="Administrator", commit=False
        )
        self.assertEqual(frappe.db.get_value("Chat Conversation", name, "title"), "check this")


class TestRepeatedReplies(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.conversation = create_conversation("ProsAlly", "repeat probe", "Administrator", commit=False)

    def _turn(self, asked, reply, metadata=None):
        save_user_message(self.conversation, asked)
        name = save_bot_message(self.conversation, reply, metadata=metadata)
        return frappe.db.get_value("Chat Message", name, ["text", "metadata"], as_dict=True)

    def test_the_same_reply_twice_says_what_is_missing_instead(self):
        self._turn("Draw my leave process", "Tell me a bit more about the process.")
        second = self._turn("Draw my leave process", "Tell me a bit more about the process.")

        self.assertIn('I cannot do "Draw my leave process" with what I have', second.text)
        self.assertEqual(
            json.loads(second.metadata)["repeat_reply"]["text"], "Tell me a bit more about the process."
        )

    def test_a_third_time_says_still(self):
        for _ in range(2):
            self._turn("Draw my leave process", "Tell me a bit more about the process.")
        third = self._turn("Draw my leave process", "Tell me a bit more about the process.")

        self.assertIn('I still cannot do "Draw my leave process"', third.text)

    def test_a_requested_repeat_is_kept(self):
        self._turn("What is the rule?", "Leave needs a manager's approval.")
        again = self._turn("Can you say that again?", "Leave needs a manager's approval.")

        self.assertEqual(again.text, "Leave needs a manager's approval.")

    def test_the_same_words_with_a_new_diagram_are_kept(self):
        self._turn("Add a step", "I've updated the process.", {"agent_result": {"bpmn_xml": "<a/>"}})
        second = self._turn("Add another", "I've updated the process.", {"agent_result": {"bpmn_xml": "<b/>"}})

        self.assertEqual(second.text, "I've updated the process.")

    def test_the_run_that_repeated_is_tagged(self):
        instance = frappe.new_doc("BPMN Process Instance")
        instance.context_doctype = "Chat Conversation"
        instance.context_docname = self.conversation
        instance.status = "Active"
        instance.db_insert()
        self._turn("Draw my leave process", "Tell me a bit more about the process.")
        save_user_message(self.conversation, "Draw my leave process")
        run = frappe.get_doc(
            {
                "doctype": "AI Agent Run",
                "instance": instance.name,
                "bpmn_id": "run_prosally_agent",
                "status": "Success",
                "started_at": frappe.utils.now_datetime(),
            }
        ).insert()

        save_bot_message(self.conversation, "Tell me a bit more about the process.")

        self.assertIn("repeat_reply", frappe.db.get_value("AI Agent Run", run.name, "_user_tags") or "")
