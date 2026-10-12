# Data notes

## Customer attributes change between orders
One customer ID can have a different segment, gender, and country on different orders. Panorama uses these attributes as values "at the time of the order". A breakdown by segment counts each order in the segment that the order shows. A customer is not fixed to one segment.

## Shipping days do not depend on the shipping method
In this data, a faster shipping method does not deliver faster. The region controls the delivery time: some regions are fast and some regions are slow for every method. Overnight shipping costs much more than Economy shipping but takes about the same number of days.

## Profit does not include the shipping cost
Profit is revenue minus cost. The shipping cost is not part of the profit. Panorama shows "profit after shipping" only as an estimate, because the data does not say who pays the shipping.

## The average of the margin column is not the margin
The Profit_Margin_% column has one value for each order. The plain average of this column gives a small order the same weight as a large order. Panorama always uses the weighted margin: the sum of profit divided by the sum of revenue.

## Revenue includes cancelled and returned orders
The revenue column has a value for every order, also for cancelled and returned orders. Panorama has three revenue metrics: gross revenue (all statuses), net revenue (without cancelled and returned orders), and realized revenue (delivered orders only).

## The order status is a snapshot
Some orders from 2021 still have the status Processing. The status shows the state at the time of the export. It is not the final state of the order.

## High discounts lose money
Small discounts keep a positive margin. Loss orders appear at high discount levels, and at the highest discount levels most orders lose money. The discount ladder on the Profitability page shows this for your data.
