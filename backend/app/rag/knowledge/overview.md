# Dataset overview

## What the data is
The dataset is an e-commerce sales log. Each row is one order with one product. The data has orders from January 2021 to December 2024 in four regions (Asia, Europe, Middle East, North America) and eighteen countries. The products are in five categories: Electronics, Clothing, Home & Kitchen, Books & Media, and Beauty & Health.

## One row is one order
An order has an order ID, an order date, the customer ID, the customer gender and segment at the time of the order, the country and region, the product with its sub-category and category, the unit price, the quantity, the discount, the revenue, the cost, the profit, the shipping cost, the shipping method, the shipping days, the payment method, and the order status.

## Hierarchies
Geography: Region → Country. Each country belongs to one region. Products: Category → Sub-category → Product. Each product belongs to one sub-category, and each sub-category belongs to one category. A drill-down follows these hierarchies.

## Time
"Today" in Panorama is the last date in the data, not the calendar date. Periods such as "last 12 months" and "year to date" count back from this date. Order volume grows during 2021, is stable in 2023, and decreases from the second quarter of 2024. Comparisons that include these months can mislead.

## Order statuses
An order has one of four statuses: Delivered, Processing, Returned, or Cancelled. The status is a snapshot at the time of the data export. Some old orders still show Processing.

## The large dataset
Panorama can also run on a generated dataset with one million orders. The generator keeps the same regions, countries, products, statuses, monthly pattern, and product mix as the original data. The large dataset is synthetic and is only for scale tests.

## Where the numbers come from
Every number in Panorama comes from one metric registry and from your own data scope. Dashboards, exports, and the assistant use the same definitions. The assistant never calculates numbers itself: the engine calculates them, and the assistant only describes them.
