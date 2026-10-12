# Access and roles

## Why can I see only some data
Panorama shows each user only the rows and columns that the role allows. The server checks every request, every export, and every assistant answer. The interface hides items only for convenience.

## Regional managers
A regional manager sees only the orders of the own region, for all categories. A regional manager does not see company totals or other regions, because a subtraction could show the numbers of other regions.

## Category managers
A category manager sees only the orders of the own category, in all regions. A category manager does not see company totals or other categories.

## Sales analysts
A sales analyst sees all orders and all metrics, but the customer IDs are pseudonyms that start with "C-". The pseudonym is the same for the same customer, so repeat buying is still visible.

## Operations and support
Operations users see all orders, statuses, shipping, returns, cancellations, and payment data. They do not see cost, profit, margin, or loss data. They see the real customer ID for support lookups.

## Executives and admins
Executives and admins see all data. Only admins can open the administration pages: users, the audit log, the system page, and the AI quality page.

## What happens with a request outside my scope
A filter or a question about data outside your scope gets a refusal. The audit log records it. An order outside your scope gives the same answer as an order that does not exist.

## The audit log
Panorama records sign-ins, failed sign-ins, exports, assistant questions, and refused requests. Admins can read and export the audit log.
