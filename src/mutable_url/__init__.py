# Networking support

"""mutable_url library

Provides the MutableURL class for URL manipulation tasks.
 - regular constructor takes a string URL
 - from_parts constructor takes named parameters to set via fields
   - MutableURL('https://www.spodhuis.org')
   - MutableURL.from_parts(host='www.spodhuis.org', scheme='https')

IDNA note: by default hostname encode/decode uses Python's stdlib 'idna'
codec, which implements IDNA2003 (RFC 3490).  For IDNA2008 (RFC 5891) -
needed for some newer TLDs and stricter validity rules - call
configure_idna() with encode/decode callables backed by the third-party
'idna' package (pip install idna).  Example:

   import idna
   import mutable_url
   mutable_url.configure_idna(
       encode=lambda h: idna.encode(h, alabel=True).decode('ascii'),
       decode=lambda h: idna.decode(h),
   )

The module never imports 'idna' itself; configure_idna() is the sole
injection point for that dependency.
"""

__author__ = 'phil@pennock-tech.com (Phil Pennock)'
__credits__ = [
    'Claude Sonnet (Anthropic) — urllib.parse rewrite, IDNA/encoding logic',
]

# Uses urllib.parse (stdlib) throughout; no third-party dependencies by default.
#
# Field naming conventions supported:
#   urllib3-style      : scheme, auth, host, port, path, query, fragment
#   urllib.parse-style : hostname (≡ host but unicode/IDNA-decoded, writable),
#                        username, password (percent-decoded, writable),
#                        netloc, request_uri

import typing
import urllib.parse

QueryParamList  = list[tuple[str, str | None]]
QueryParamDict  = dict[str, str | None]
QueryParamMulti = dict[str, list[str | None]]

__all__ = []


def export(f):
    __all__.append(f.__name__)
    return f


# ---------------------------------------------------------------------------
# Userinfo (username / password) percent-encoding helpers
# ---------------------------------------------------------------------------

# RFC 3986 §3.2.1 — characters that may appear unencoded in userinfo:
#   unreserved  = ALPHA / DIGIT / "-" / "." / "_" / "~"
#   sub-delims  = "!" / "$" / "&" / "'" / "(" / ")" / "*" / "+" / "," / ";" / "="
# ":" additionally separates user from password, so it must be encoded within
# the username component but may appear unencoded in the password component.
_USERINFO_SAFE_USER = "-._~!$&'()*+,;="      # colon NOT safe in username
_USERINFO_SAFE_PASS = "-._~!$&'()*+,;=:"     # colon safe in password


def _encode_userinfo(value: str, *, is_password: bool = False) -> str:
    """Percent-encode a plain-text username or password for embedding in a URL."""
    safe = _USERINFO_SAFE_PASS if is_password else _USERINFO_SAFE_USER
    return urllib.parse.quote(value, safe=safe)


def _decode_userinfo(raw: str) -> str:
    """Percent-decode a raw userinfo component to a plain-text string."""
    return urllib.parse.unquote(raw)


# ---------------------------------------------------------------------------
# Hostname / IDNA helpers — default IDNA2003 (stdlib) implementations
# ---------------------------------------------------------------------------

def _is_ip_literal(host: str) -> bool:
    """Return True for IPv6 bracket literals or bare IPv4 dotted-decimal."""
    if not host:
        return False
    if host.startswith('['):        # IPv6: [::1]
        return True
    parts = host.rstrip('.').split('.')
    if len(parts) == 4:
        try:
            return all(0 <= int(p) <= 255 for p in parts)
        except ValueError:
            pass
    return False


def _default_encode_host(host: str | None) -> str | None:
    """Encode a (possibly unicode) hostname to ASCII-Compatible Encoding.

    Pure-ASCII hostnames and IP literals pass through unchanged.  Encoding
    failures fall back to the original string so that already-encoded or
    otherwise non-encodable hosts are not silently lost.

    Uses IDNA2003 (Python stdlib 'idna' codec).  Replace via configure_idna()
    if you need IDNA2008.
    """
    if not host or _is_ip_literal(host):
        return host
    try:
        host.encode('ascii')
        return host                 # already ASCII — nothing to do
    except UnicodeEncodeError:
        pass
    try:
        return host.encode('idna').decode('ascii')
    except (UnicodeError, UnicodeDecodeError):
        return host                 # best-effort fallback


def _default_decode_host(host: str | None) -> str | None:
    """Decode a punycode / ACE hostname to its unicode form.

    Pure-unicode or non-punycode labels pass through unchanged.  IP literals
    are returned as-is.

    Uses IDNA2003 (Python stdlib 'idna' codec).  Replace via configure_idna()
    if you need IDNA2008.
    """
    if not host or _is_ip_literal(host):
        return host
    try:
        return host.encode('ascii').decode('idna')
    except (UnicodeError, UnicodeDecodeError):
        return host


# ---------------------------------------------------------------------------
# Module-level IDNA dispatch hooks
#
# All internal code calls _encode_host / _decode_host rather than the
# _default_* functions directly, so that configure_idna() takes effect
# everywhere without callers needing to do anything.
# ---------------------------------------------------------------------------

_encode_host = _default_encode_host
_decode_host = _default_decode_host


@export
def configure_idna(
    *,
    encode: 'typing.Callable[[str | None], str | None]',
    decode: 'typing.Callable[[str | None], str | None]',
) -> None:
    """Replace the module-level IDNA encode/decode hooks.

    Both callables receive a hostname string (or None) and must return a
    hostname string (or None).  They are responsible for handling IP literals
    and None themselves, or they may delegate to _is_ip_literal() for that
    guard.

    Typical usage with the 'idna' package (IDNA2008):

        import idna
        import mutable_url

        def _enc(host):
            if host is None or mutable_url._is_ip_literal(host):
                return host
            try:
                return idna.encode(host, alabel=True).decode('ascii')
            except idna.core.InvalidCodepoint:
                return host  # or raise, depending on your policy

        def _dec(host):
            if host is None or mutable_url._is_ip_literal(host):
                return host
            try:
                return idna.decode(host)
            except (idna.core.InvalidCodepoint, UnicodeError):
                return host

        mutable_url.configure_idna(encode=_enc, decode=_dec)

    This function is the *only* place where an IDNA2008 dependency is wired
    in; the module itself never imports 'idna'.
    """
    global _encode_host, _decode_host
    _encode_host = encode
    _decode_host = decode


# ---------------------------------------------------------------------------
# Query-string parsing / serialisation helpers
# ---------------------------------------------------------------------------

def _parse_query_params(query: str | None) -> QueryParamList:
    """Parse a raw query string into an ordered list of (key, value) pairs.

    Decoding uses ``urllib.parse.unquote_plus``, which converts ``%XX``
    sequences *and* ``+`` to spaces — the standard behaviour for
    ``application/x-www-form-urlencoded`` data (HTML forms, most REST APIs).
    Use ``MutableURL.query`` when you need the raw, still-encoded string.

    Value semantics:

    * ``?flag``      → ``("flag", None)``   — no ``=`` sign at all
    * ``?flag=``     → ``("flag", "")``     — ``=`` present but value is empty
    * ``?flag=v``    → ``("flag", "v")``    — normal key-value pair
    * Empty segments (consecutive ``&`` separators) are silently skipped.
    """
    if not query:
        return []
    result: QueryParamList = []
    for part in query.split('&'):
        if not part:
            continue
        if '=' in part:
            raw_k, raw_v = part.split('=', 1)
            result.append((
                urllib.parse.unquote_plus(raw_k),
                urllib.parse.unquote_plus(raw_v),
            ))
        else:
            result.append((urllib.parse.unquote_plus(part), None))
    return result


class _QueryParamView(dict):
    """dict subclass returned by ``query_params``; subscript assignment writes back to the URL.

    This ensures that ``u.query_params['key'] = value`` actually mutates the URL
    rather than silently mutating a discarded copy.  Values are coerced to ``str``
    (or left as ``None`` to produce a valueless ``key``-only parameter).
    """

    __slots__ = ('_setter',)

    def __init__(self, setter, data: 'QueryParamDict') -> None:
        super().__init__(data)
        self._setter = setter   # callable: _set_query_params(dict)

    def __setitem__(self, key: str, value) -> None:
        coerced = None if value is None else str(value)
        super().__setitem__(key, coerced)
        self._setter(self)


def _encode_query_params(params: QueryParamList) -> str | None:
    """Encode a list of (key, value) pairs into a raw query string.

    Encoding uses ``urllib.parse.quote_plus``, which encodes spaces as ``+``
    and percent-encodes everything else — the inverse of ``unquote_plus``.

    * A ``None`` value produces a key-only parameter (no ``=`` sign).
    * An empty-string value produces ``key=``.
    * Returns ``None`` (not ``""``) when *params* is empty, consistent with
      how the rest of ``MutableURL`` represents absent components.
    """
    if not params:
        return None
    parts: list[str] = []
    for k, v in params:
        k_enc = urllib.parse.quote_plus(k)
        if v is None:
            parts.append(k_enc)
        else:
            parts.append(f'{k_enc}={urllib.parse.quote_plus(v)}')
    return '&'.join(parts) or None


# ---------------------------------------------------------------------------
# Internal URL value object
# ---------------------------------------------------------------------------

class _URL:
    """Lightweight URL value object backed by individual RFC 3986 components.

    ``auth`` stores the raw percent-encoded userinfo string exactly as it
    appears in the URL (e.g. ``"user%40corp:p%40ss"``).  Callers that need
    decoded values should use MutableURL's ``username``/``password``
    properties.

    ``host`` stores the ASCII/punycode (ACE) form of the hostname so that
    ``__str__`` always produces a valid ASCII URL.  MutableURL's ``hostname``
    property handles unicode ↔ IDNA conversion for human-facing access.
    """
    __slots__ = ('scheme', 'auth', 'host', 'port', 'path', 'query', 'fragment')

    def __init__(self, scheme=None, auth=None, host=None, port=None,
                 path=None, query=None, fragment=None):
        self.scheme   = scheme   or None
        self.auth     = auth     or None
        self.host     = host     or None
        self.port     = int(port) if port is not None else None
        self.path     = path     or None
        self.query    = query    or None
        self.fragment = fragment or None

    @property
    def netloc(self) -> str | None:
        """Reconstructed ``[userinfo@]host[:port]`` component."""
        if not self.host:
            return None
        nl = self.host
        if self.port is not None:
            nl = f'{nl}:{self.port}'
        if self.auth:
            nl = f'{self.auth}@{nl}'
        return nl

    @property
    def request_uri(self) -> str:
        """Path and query string combined, as used in an HTTP request line."""
        uri = self.path or '/'
        if self.query:
            uri = f'{uri}?{self.query}'
        return uri

    @property
    def url(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return urllib.parse.urlunsplit(urllib.parse.SplitResult(
            scheme   = self.scheme   or '',
            netloc   = self.netloc   or '',
            path     = self.path     or '',
            query    = self.query    or '',
            fragment = self.fragment or '',
        ))

    def __repr__(self) -> str:
        return (f'_URL(scheme={self.scheme!r}, auth={self.auth!r}, '
                f'host={self.host!r}, port={self.port!r}, path={self.path!r}, '
                f'query={self.query!r}, fragment={self.fragment!r})')


def _parse_url(u: str) -> _URL:
    """Parse a URL string into a _URL, preserving percent-encoding in auth."""
    p = urllib.parse.urlsplit(u)

    # Extract raw userinfo from netloc rather than using p.username / p.password:
    # the latter are *decoded* by urllib.parse, so reconstructing auth from them
    # would corrupt credentials containing percent-encoded characters (e.g. a
    # literal '@' encoded as '%40').
    auth = None
    if '@' in p.netloc:
        raw_userinfo, _ = p.netloc.rsplit('@', 1)
        auth = raw_userinfo or None

    # Always store host in ASCII/punycode form so __str__ produces a valid URL
    # even when the caller supplies a unicode (IDN) hostname.  Goes through the
    # hook so any configure_idna() call is respected at parse time too.
    #
    # Re-wrap IPv6 addresses in brackets: urlsplit strips them from
    # p.hostname (e.g. '[::1]' in the URL becomes '::1' in p.hostname),
    # but we need brackets for correct URL reconstruction via netloc.
    host_str = p.hostname or None
    if host_str and ':' in host_str:
        host_str = f'[{host_str}]'
    host = _encode_host(host_str)

    return _URL(
        scheme   = p.scheme   or None,
        auth     = auth,
        host     = host,
        port     = p.port,       # already int-or-None from urlsplit
        path     = p.path     or None,
        query    = p.query    or None,
        fragment = p.fragment or None,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@export
class MutableURL(object):
    """Mutable URL object; every component field can be set.

    Optimised for fast lookup: every mutation of a base field reconstructs the
    internal _URL so that derived properties (netloc, url, …) remain cheap.

    Mutable fields — urllib3-style (raw/encoded values, no implicit transform):
        scheme, auth, host, port, path, query, fragment

    Mutable fields — urllib.parse-style (encode/decode transparently):
        hostname   unicode ↔ IDNA/punycode; delegates storage to ``host``
        username   decoded plain-text; encodes on write, updates ``auth``
        password   decoded plain-text; encodes on write, updates ``auth``

    Read-only computed fields (present in both conventions):
        netloc, request_uri, url

    Query-parameter dict views (all decode via ``unquote_plus``):
        query_params        dict[str, str|None]       last-value-wins; writable
        query_params_list   list[tuple[str, str|None]] ordered, lossless; writable
        query_params_multi  dict[str, list[str|None]]  all values per key; read-only

    Relationship between ``host`` and ``hostname``:
        ``host`` is the storage/wire-format field: ASCII/ACE only, suitable
        for direct URL embedding.  ``hostname`` is the presentation-layer
        counterpart: accepts and returns unicode, performs IDNA encode/decode
        via the module-level hooks (IDNA2003 by default; see configure_idna()).
        Setting ``hostname = "münchen.de"`` stores ``"xn--mnchen-3ya.de"`` in
        ``host``; reading ``hostname`` on that URL returns ``"münchen.de"``.
        Use ``host`` when you already have a correctly encoded ASCII hostname;
        use ``hostname`` for everything human-facing.

    Relationship between ``auth``, ``username``, and ``password``:
        ``auth`` holds the raw percent-encoded userinfo string
        (e.g. ``"user%40corp:s3cr%3At"``).  Assign to it directly when you
        already have a correctly encoded string.  ``username`` and ``password``
        accept plain unicode, encode it for you, and splice only their half
        into ``auth`` without touching or re-encoding the other half.
    """

    _FIELDS = ('scheme', 'auth', 'host', 'port', 'path', 'query', 'fragment')

    def __init__(self, u: str):
        self._u = _parse_url(u)

    @classmethod
    def from_parts(
        cls,
        *,
        scheme: str | None = None,
        host: str | None = None,
        hostname: str | None = None,
        port: int | None = None,
        auth: str | None = None,
        username: str | None = None,
        password: str | None = None,
        path: str | None = None,
        query: str | None = None,
        query_params: 'QueryParamDict | None' = None,
        query_params_list: 'QueryParamList | None' = None,
        fragment: str | None = None,
    ) -> 'MutableURL':
        """Construct a MutableURL directly from its component parts.

        All parameters are keyword-only.  Omitted parameters default to None
        (absent from the resulting URL).  Three groups of parameters are
        mutually exclusive — passing more than one from any group raises
        ValueError:

            host / hostname
                ``host`` accepts a pre-encoded ASCII/ACE hostname (stored
                as-is).  ``hostname`` accepts a unicode hostname and
                IDNA-encodes it via the module-level hook (see
                configure_idna()), exactly as the ``hostname`` setter does.

            auth / (username, password)
                ``auth`` accepts a raw percent-encoded userinfo string such as
                ``"user%40corp:s3cr%3At"`` (stored as-is).
                ``username`` and ``password`` accept plain-text strings and
                percent-encode them before storage; either may be omitted
                independently.  Supplying only ``password`` (with no
                ``username``) produces a ``:token`` userinfo, which is the
                conventional form for bearer-token credentials in REST APIs.

            query / query_params / query_params_list
                ``query`` accepts a raw query string (no leading ``?``).
                ``query_params`` accepts a ``dict[str, str | None]``; key
                order follows dict iteration order.
                ``query_params_list`` accepts a
                ``list[tuple[str, str | None]]`` for precise ordering or
                multi-value keys.
                All three encode via ``quote_plus``, matching the
                ``query_params*`` property behaviour.  An empty dict or list
                produces no query string (same as omitting the parameter).
        """
        # -- mutual exclusion -------------------------------------------------
        if host is not None and hostname is not None:
            raise ValueError("host and hostname are mutually exclusive")
        if auth is not None and (username is not None or password is not None):
            raise ValueError("auth and username/password are mutually exclusive")
        n_query = sum(x is not None for x in (query, query_params, query_params_list))
        if n_query > 1:
            raise ValueError(
                "query, query_params, and query_params_list are mutually exclusive"
            )

        # -- resolve host -----------------------------------------------------
        resolved_host = host
        if hostname is not None:
            resolved_host = _encode_host(hostname)

        # -- resolve auth -----------------------------------------------------
        resolved_auth = auth
        if username is not None or password is not None:
            raw_user = (
                _encode_userinfo(username, is_password=False)
                if username is not None
                else ''
            )
            if password is not None:
                resolved_auth = f'{raw_user}:{_encode_userinfo(password, is_password=True)}'
            else:
                resolved_auth = raw_user or None

        # -- resolve query ----------------------------------------------------
        resolved_query = query
        if query_params is not None:
            resolved_query = _encode_query_params(list(query_params.items()))
        elif query_params_list is not None:
            resolved_query = _encode_query_params(query_params_list)

        obj = cls.__new__(cls)
        obj._u = _URL(
            scheme=scheme,
            auth=resolved_auth,
            host=resolved_host,
            port=port,
            path=path,
            query=resolved_query,
            fragment=fragment,
        )
        return obj

    # -- internal helpers ----------------------------------------------------

    def _setter_for(self, new_field):
        """Return a setter that rebuilds _u with one field replaced.

        Field values are read from self._u at *call* time (not at the time
        _setter_for is invoked) so that interleaved mutations compose
        correctly.
        """
        other_fields = [f for f in type(self)._FIELDS if f != new_field]

        def _f(s, new_value):
            params = {f: getattr(s._u, f) for f in other_fields}
            params[new_field] = new_value
            s._u = _URL(**params)

        return _f

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MutableURL):
            return NotImplemented
        return (self._u.scheme, self._u.auth, self._u.host, self._u.port,
                self._u.path, self._u.query, self._u.fragment) == (
                other._u.scheme, other._u.auth, other._u.host, other._u.port,
                other._u.path, other._u.query, other._u.fragment)

    def __str__(self) -> str:
        return str(self._u)

    def __repr__(self) -> str:
        return f"MutableURL('{self}')"

    # -- mutable base fields (urllib3-style) ----------------------------------

    scheme = property(lambda s: s._u.scheme,
                      lambda s, v: s._setter_for('scheme')(s, v))
    # auth: raw percent-encoded userinfo string; prefer username/password for
    # plain-text assignment.
    auth   = property(lambda s: s._u.auth,
                      lambda s, v: s._setter_for('auth')(s, v))
    # host: ASCII/ACE hostname; prefer hostname for unicode/IDN assignment.
    host   = property(lambda s: s._u.host,
                      lambda s, v: s._setter_for('host')(s, v))
    port   = property(lambda s: s._u.port,
                      lambda s, v: s._setter_for('port')(s, v))
    path   = property(lambda s: s._u.path,
                      lambda s, v: s._setter_for('path')(s, v))
    query  = property(lambda s: s._u.query,
                      lambda s, v: s._setter_for('query')(s, v))
    fragment = property(lambda s: s._u.fragment,
                        lambda s, v: s._setter_for('fragment')(s, v))

    # -- mutable derived fields (urllib.parse-style) --------------------------

    def _get_hostname(self) -> str | None:
        """Unicode (IDNA-decoded) hostname; passes through IP literals unchanged.

        Decodes via the module-level _decode_host hook; see configure_idna().
        """
        return _decode_host(self._u.host)

    def _set_hostname(self, value: str | None) -> None:
        """Set hostname from a unicode or ACE string; IDNA-encodes before storage.

        Encodes via the module-level _encode_host hook; see configure_idna().
        Assigning None clears the host entirely.
        """
        self.host = _encode_host(value) if value is not None else None

    hostname = property(_get_hostname, _set_hostname)

    def _get_username(self) -> str | None:
        """Percent-decoded username, or None if no userinfo is present."""
        if self._u.auth is None:
            return None
        raw = self._u.auth.split(':', 1)[0]
        return _decode_userinfo(raw) if raw else None

    def _set_username(self, value: str | None) -> None:
        """Set the username from a plain-text (unicode) string.

        Percent-encodes the new value.  Preserves the existing raw-encoded
        password verbatim so it is never double-encoded.  Passing None removes
        the username while retaining any existing password.
        """
        # Preserve the raw-encoded password without touching it.
        raw_pass: str | None = None
        if self._u.auth and ':' in self._u.auth:
            raw_pass = self._u.auth.split(':', 1)[1]

        if value is None:
            self.auth = (f':{raw_pass}' if raw_pass is not None else None)
        else:
            encoded = _encode_userinfo(value, is_password=False)
            self.auth = (f'{encoded}:{raw_pass}'
                         if raw_pass is not None
                         else encoded)

    username = property(_get_username, _set_username)

    def _get_password(self) -> str | None:
        """Percent-decoded password, or None if not present."""
        if self._u.auth is None or ':' not in self._u.auth:
            return None
        raw = self._u.auth.split(':', 1)[1]
        return _decode_userinfo(raw) if raw else None

    def _set_password(self, value: str | None) -> None:
        """Set the password from a plain-text (unicode) string.

        Percent-encodes the new value.  Preserves the existing raw-encoded
        username verbatim so it is never double-encoded.  Passing None removes
        the password while retaining any existing username.
        """
        # Preserve the raw-encoded username without touching it.
        raw_user: str = ''
        if self._u.auth:
            raw_user = self._u.auth.split(':', 1)[0]

        if value is None:
            # Drop the password; clear auth entirely if username is also absent.
            self.auth = raw_user or None
        else:
            encoded = _encode_userinfo(value, is_password=True)
            self.auth = f'{raw_user}:{encoded}'

    password = property(_get_password, _set_password)

    # -- query-parameter dict views -------------------------------------------

    def _get_query_params(self) -> QueryParamDict:
        """Query parameters as a ``dict``; for repeated keys the **last** value wins.

        Keys and string values are percent-decoded (``+`` treated as space via
        ``unquote_plus``).  A parameter without an ``=`` sign (e.g. ``flag``
        in ``?flag&x=1``) maps to ``None``; a parameter whose value is the
        empty string (e.g. ``x`` in ``?x=``) maps to ``""`` — the two cases
        are distinct.

        Repeated-key policy: last-value-wins mirrors Python ``dict`` construction
        semantics and is the safest choice when callers know keys are unique.
        Use :attr:`query_params_multi` when you need all values.

        Setting this property replaces the **entire** query string.  Key order
        follows iteration order of the source dict (insertion-ordered in Python
        3.7+).  To control key order precisely or preserve multi-values, set
        :attr:`query_params_list` instead.
        """
        return _QueryParamView(self._set_query_params, dict(_parse_query_params(self._u.query)))

    def _set_query_params(self, params: QueryParamDict) -> None:
        self.query = _encode_query_params(list(params.items()))

    query_params = property(_get_query_params, _set_query_params)

    def _get_query_params_list(self) -> QueryParamList:
        """Query parameters as an ordered list of ``(key, value)`` pairs.

        This is the lossless representation: every parameter appears in its
        original position, repeated keys are preserved, and the ``None`` /
        ``""`` distinction for valueless parameters is maintained.  Keys and
        string values are percent-decoded (``+`` treated as space).

        Setting this property replaces the **entire** query string from the
        supplied list.  ``None`` values serialise without an ``=`` sign;
        ``""`` values serialise as ``key=``.
        """
        return _parse_query_params(self._u.query)

    def _set_query_params_list(self, params: QueryParamList) -> None:
        self.query = _encode_query_params(params)

    query_params_list = property(_get_query_params_list, _set_query_params_list)

    @property
    def query_params_multi(self) -> QueryParamMulti:
        """Query parameters as a ``dict`` mapping each key to a list of all its values.

        All occurrences of a repeated key are collected into a list in the
        order they appear in the query string.  The ``None`` / ``""``
        distinction is preserved within each list.  Keys and string values are
        percent-decoded (``+`` treated as space).

        This property is **read-only**.  To set multi-value parameters, assign
        to :attr:`query_params_list` with the desired ``(key, value)`` pairs.

        Example::

            url = MutableURL("https://example.com/search?color=red&color=blue&lang=en")
            url.query_params_multi
            # {"color": ["red", "blue"], "lang": ["en"]}
        """
        result: QueryParamMulti = {}
        for k, v in _parse_query_params(self._u.query):
            result.setdefault(k, []).append(v)
        return result

    # -- read-only computed fields (both conventions) -------------------------

    netloc      = property(lambda s: s._u.netloc)
    request_uri = property(lambda s: s._u.request_uri)
    url         = property(lambda s: s._u.url)


# vim: set sw=4 et :
# EOF
