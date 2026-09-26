# Sample Queries

Use these after authenticating and, for semantic examples, completing a workspace sync. Results depend on the connected Google account.

## Gmail

1. `Show my 5 latest emails.`
2. `Find my latest 5 unread emails.`
3. `Find emails about Project Atlas from the last 30 days.`

## Calendar

4. `What's on my calendar tomorrow?`
5. `Find my next meeting.`
6. `Show calendar events between Monday morning and Friday evening.`

## Drive

7. `Show my 5 most recently modified Drive files.`
8. `Find recent PDFs in my Drive.`
9. `Find Drive files related to Project Atlas.`

## Multi-service orchestration

10. `Show my 3 latest emails, tomorrow's calendar events, and 3 recently modified Drive files.`
11. `Prepare me for my next meeting.`
12. `Find my next Project Atlas meeting, then find related emails and Drive documents.`

## Conversation context

First turn:

> Find my next meeting with the Project Atlas team.

Follow-up using the same conversation:

> Now find related emails and files and summarize what I should review.

## Clarification behavior

13. `Move my meeting with Aman.`

The backend should ask for the missing new date/time, and may also clarify the target if multiple meetings match. The follow-up must reuse the same `conversation_id`.

## Safe writes

These produce a stored proposal and require explicit approval before Google is changed:

14. **Approval required:** `Create a Demo Meeting tomorrow at 2 PM.`
15. **Approval required:** `Schedule a Google Meet with demo@example.com tomorrow at 10 AM.`
16. **Approval required:** `Delete my Demo Meeting tomorrow.`

Always inspect the approval preview before approving. For a demonstration, use an account and attendee address intended for testing.
