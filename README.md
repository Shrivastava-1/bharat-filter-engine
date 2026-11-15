# 🇮🇳 Bharat Filter Engine

A generic, configuration‑driven filtering engine for Ruby on Rails
`ActiveRecord` applications. Instead of hand‑rolling `where` clauses
for every index action, you declare a **filter config** once and let
the engine turn incoming params (from a form, an API request, a
query string) into a filtered `ActiveRecord::Relation` — including
filters on associated models, free‑text search, and dynamically
populated dropdown values.

[![Gem Version](https://img.shields.io/badge/version-0.2.0-blue)](CHANGELOG.md)  
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Table of contents

- [Features](#features)
- [Installation](#installation)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Filter config reference](#filter-config-reference)
- [Filter types with examples](#filter-types-with-examples)
  - [string](#string)
  - [array](#array)
  - [boolean](#boolean)
  - [integer / float](#integer--float)
  - [daterange](#daterange)
  - [search](#search)
- [Nested / association filters](#nested--association-filters)
- [Free‑text search (`search` filter type)](#free-text-search-search-filter-type)
- [Dynamic filter values (for dropdowns)](#dynamic-filter-values-for-dropdowns)
- [Full Rails controller example](#full-rails-controller-example)
- [Legacy config format](#legacy-config-format)
- [Error handling](#error-handling)
- [Running the test suite](#running-the-test-suite)
- [Contributing](#contributing)
- [Development](#development)
- [License](#license)

---

## Features

- String, array (multi‑select), boolean, integer, and float filters  
- Greater‑than‑or‑equal / less‑than‑or‑equal numeric range filters  
- Date range filters (hash, array, or comma‑separated string input)  
- Nested / multi‑level association filters (`lead__client__name`)  
- Free‑text search across multiple columns, including associations  
- `field=value` search syntax with `&` (AND) / `|` (OR) grouping  
- Dynamic filter values (distinct column values, e.g. to populate a dropdown) for both direct and nested/associated columns  
- Automatically ignores blank params so existing scope chains and default ordering are left untouched  
- Legacy config format still supported (see below)

## Installation

Add this line to your application's `Gemfile`:

```ruby
gem "bharat_filter_engine"
```

And then run:

```bash
bundle install
```

Or install it yourself:

```bash
gem install bharat_filter_engine
```

**Requirements:** Ruby >= 3.0, ActiveRecord/ActiveModel/ActiveSupport >= 6.1.

## Quick start

```ruby
# 1. Define a filter config for your model (usually a constant or a
#    method on the model/controller).
FILTER_CONFIG = {
  stage: {
    type: :single,
    filter_type: :string,
    dbcolumn: :stage
  },

  status: {
    type: :single,
    filter_type: :array,
    dbcolumn: :approval_status
  },

  amount: {
    type: :single,
    filter_type: :integer,
    dbcolumn: :amount,
    range_type: :gte
  }
}

# 2. Apply it to a scope using whatever params your app received.
result = BharatFilterEngine.apply(
  scope: Sale.all,
  config: FILTER_CONFIG,
  params: {
    stage: "qualified",
    status: ["approved", "pending"],
    amount: "500"
  }
)

result # => an ActiveRecord::Relation, filtered and ready to use
```

That's it — `result` behaves exactly like any other `ActiveRecord::Relation`,
so you can keep chaining `.order`, `.page`, `.includes`, etc.

## How it works

`BharatFilterEngine.apply` takes three keyword arguments:

| Argument | Type                     | Description
