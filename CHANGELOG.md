# Changelog

All notable changes to this project will be documented here.

## [0.2.0]

### Added

- Presence filters for checking whether a column contains a value. String
  columns treat both `NULL` and empty strings as blank; non-string columns
  distinguish `NULL` from valid values such as numeric zero.
- Negated filters for excluding matching string, array, boolean, and exact
  numeric values. Negation is also supported for nested association filters.
- Text-based search for record IDs, allowing searches such as `id=42`.
- Dynamic filter-value lookups with optional partial-term matching and result
  limits. Lookups support direct fields and multi-level association fields.
- Multi-level association resolution using `__` paths, including paths used by
  nested filters, search, and dynamic filter-value lookups.
- Association join tracking to handle different association paths that reach
  the same table. Where a plain join could incorrectly combine conditions
  across associations, the engine uses subqueries to keep each condition tied
  to its intended association path.
- Configuration validation for supported filter types, range types, required
  columns, nested associations, and incompatible option combinations.

### Improved

- Numeric filters validate input before applying exact, `gte`, `lte`, or
  `between` comparisons. Between filters accept hash, array, and
  comma-separated bounds, including open-ended ranges.
- Date-range filters accept hash, array, and comma-separated inputs, and
  support open-ended ranges. Date-only bounds are expanded to the beginning
  or end of the corresponding day.
- Parameter normalization supports comma-separated arrays and JSON-encoded
  arrays while preserving boolean `false` as a meaningful filter value.
- Search validates configured fields and does not silently discard an
  unmatchable AND group. An invalid or unconfigured field in a group cannot
  cause the search to return unrelated records.
- Search escapes SQL LIKE wildcard characters (`%` and `_`) so they are
  treated as literal characters in user-provided terms.
- Nested filters apply `DISTINCT` to avoid duplicate result records caused by
  association joins.
- Dynamic filter values return distinct, ordered, non-blank values and can
  filter those values by a case-insensitive partial term.
- Legacy filter configuration remains supported through automatic
  normalization to the modern configuration format.
- Shared filtering conditions are handled through a common `apply_condition`
  helper, reducing repeated query-building logic.

### Fixed

- Negated array filtering handles arrays containing `nil` without losing the
  intended NULL exclusion semantics.
- Association-path collisions are handled without incorrectly applying
  conditions to a different association that happens to use the same table.
- Invalid numeric input is ignored safely rather than being converted into
  an unintended numeric filter value.
- Search terms containing `%`, `_`, or the escape character are escaped
  before building LIKE conditions.

## [0.1.1] - 2026-08-19

### Fixed

- `spec/engine_spec.rb`: the top-level `client`/`lead`/`sale` fixtures
  were declared with `let!`, which forced them to be created before
  *every* example in the file -- including the many examples further
  down that build their own local `sale`/`sale_one`/`sale_two`
  records. That stray fixture record (`stage: "qualified",
  approval_status: "approved", active: true, amount: 500`) then
  satisfied several unrelated examples' filters and leaked into their
  `contain_exactly(...)` results. Switched to lazy `let` so the
  fixture is only created by the handful of examples that actually
  reference it by name.
- `SearchBuilder#field_based_search` no longer silently ignores an
  `AND` group whose field isn't in `allowed_columns`. Previously the
  whole condition was dropped and every record was returned; now that
  group is correctly treated as unmatchable and the search returns no
  records.
- Test suite: several specs under `spec/engine_spec.rb` and
  `spec/rule_normalizer_spec.rb` called `described_class.apply`/
  `described_class.new(scope: ..., allowed_columns: ...)` while
  `described_class` resolved to the wrong class (`Engine` /
  `RuleNormalizer`), so those examples raised `NoMethodError` /
  `ArgumentError` instead of testing anything. They've been moved to
  their correct spec files (`search_builder_spec.rb`,
  `dynamic_filter_values_spec.rb`, `engine_spec.rb`) and now exercise
  the intended class.

### Changed

- `Engine`: extracted the repeated table-qualified `where` branching
  from the array/boolean/string/exact-numeric filters into a single
  `apply_condition` helper.
- `DynamicFilterValues` and `SearchBuilder` now reuse a single
  `AssociationResolver` instance instead of instantiating a new one
  per call/scope.

## [0.1.0] - 2026-08-19

### Added

- Initial Bharat Filter Engine implementation.
- String filters.
- Array filters.
- Boolean filters.
- Integer filters.
- Float filters.
- Numeric range filters.
- Date range filters.
- Nested association filters.
- Multi-level nested search.
- AND / OR search.
- Dynamic filter values.
- Legacy filter configuration support.
