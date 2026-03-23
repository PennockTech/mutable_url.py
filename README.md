mutable_url.py
==============

This repository holds the source for the `mutable_url` Python package.

This provides one utility class, `MutableURL`.

It also has one hook-point, `configure_idna`, to allow callers to opt into
using correct modern DNS internationalised hostnames; the default is to use
only the IDNA support in Python stdlib, which is out of date _but_ usually
good enough.

```python
from mutable_url import MutableURL

u = MutableURL('http://www.example.org/hum')
u.scheme = https

print(u)
call_func_wanting_url(u.url)

u2 = MutableURL.from_parts(scheme='https', host='www.example.com',
                           query_params={'foo': 'bar', 'baz': '3'})
```

The `from_parts` class-method constructor requires keyword invocation.  You
can start with an empty URL.  There is no default scheme.  At present, the
query_params values must be strings.

A `MutableURL` can be reconstructed into a string form via `str()` or by using
the `.url` property (which just does that for you). This is the most stable
interface for passing into other URL handling classes: I haven't found any
other intermediate representation for cross-API compatibility worth the added
complexity.

The Authority section is supported, including further virtualized accessors to
allow individual access to `username` and `password` fields.  Either one can
be empty, to support auth schemes which only use one or the other (such as
issued tokens provided as a password for an empty user).

The hostname part has two forms, which differ only when IDNA
internationalisation is in play:
 * `host`: the on-the-wire ASCII form (ACE), which is also what appears in the URL
 * `hostname`: the presentation-layer form, as UTF-8

There are multiple accessors for query parameters handling:
 * `query_params`: a simple `dict` view which assumes keys are not repeated
 * `query_params_multi`: a dict where the value is a list of strings, one for
   each instance
 * `query_params_list`: a list of `(key,value)` tuples.

Fragments are supported.

## AI Disclosures

The original implementation of `MutableURL` was written by a human and
committed to a private repository on 2018-04-27.
That initial version depended upon `urllib3` (by way of `requests`).

On 2026-02-18, Anthropic's Claude was used to rewrite the implementation; the
code was subjected to thorough human code-review and there were many
iterations as aspects were refined.  The goal was to move to only depending
upon the Python stdlib, to add more accessors (for compatibility with API
expectations of _both_ `urllib` _and_ `urllib3`), and to add tests.  Along the
way, we also collected IDNA support, while keeping the default as stdlib-only.
