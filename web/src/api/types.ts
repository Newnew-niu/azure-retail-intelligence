// Names for the generated API types (schema.d.ts comes from openapi.json; never edit it by hand).
import type { components, operations } from './schema'

type Schemas = components['schemas']

export type SellerPage = Schemas['SellerPage']
export type SellerListItem = Schemas['SellerListItem']
export type SellerDetail = Schemas['SellerDetail']
export type SellerSummary = Schemas['SellerSummary']
export type SellerMonth = Schemas['SellerMonth']
export type HealthSignal = Schemas['HealthSignal']
export type SignalStatus = HealthSignal['status']

export type SellerListQuery = NonNullable<operations['list_sellers_sellers_get']['parameters']['query']>
export type SortKey = NonNullable<SellerListQuery['sort']>
export type SortOrder = NonNullable<SellerListQuery['order']>
