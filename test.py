import unittest
from unittest.mock import Mock, patch

from google.genai import types

from agent import process_request


class ProcessRequestTests(unittest.TestCase):

	@patch("agent.client.models.generate_content")
	def test_history_is_sent_and_updated(self, generate_content):
		generate_content.return_value = Mock(
			text='{"intent":"ACCESS_REQUEST","application":"Excel","message":"I can help with that."}'
		)
		history = [
			types.Content(
				role="user",
				parts=[types.Part.from_text(text="I need access")],
			),
			types.Content(
				role="model",
				parts=[types.Part.from_text(text="Which application do you need?")],
			),
		]

		result = process_request("I need access to Excel", history)

		self.assertEqual(result.application, "Excel")
		sent_contents = generate_content.call_args.kwargs["contents"]
		self.assertEqual(len(sent_contents), 3)
		self.assertEqual(sent_contents[0].parts[0].text, "I need access")
		self.assertEqual(sent_contents[2].parts[0].text, "I need access to Excel")
		self.assertEqual(len(history), 4)

	def test_application_follow_up_resolves_pending_clarification(self):
		history = [
			types.Content(
				role="user",
				parts=[types.Part.from_text(text="requesting access")],
			),
			types.Content(
				role="model",
				parts=[
					types.Part.from_text(
						text='{"intent":"CLARIFICATION","software":null,"application":null,"message":"Which application do you need access to?"}'
					)
				],
			),
		]

		result = process_request("Excel", history)

		self.assertEqual(result.intent.value, "ACCESS_REQUEST")
		self.assertEqual(result.application, "Excel")
		self.assertEqual(len(history), 4)

	@patch("agent.client.models.generate_content")
	def test_named_application_without_action_is_clarification(self, generate_content):
		generate_content.return_value = Mock(
			text='{"intent":"ACCESS_REQUEST","application":"DNR","message":"I can help."}'
		)

		result = process_request("I want DNR")

		self.assertEqual(result.intent.value, "CLARIFICATION")
		self.assertIsNone(result.application)
		self.assertIn("Do you need access", result.message)


if __name__ == "__main__":
	unittest.main()
