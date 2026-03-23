# tests/test_mutable_url.py
"""Tests for mutable_url.MutableURL."""

# Run directly:   python tests/test_mutable_url.py
# Run via pytest: uv run pytest tests/test_mutable_url.py -v
#
# pytest does not natively detect the pyproject.toml, so will look for an
# installed copy of the library instead of the version in-repo, unless you
# invoke via 'uv' or equivalent tooling.

import pytest

import mutable_url
from mutable_url import MutableURL

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_idna_hooks():
    """Restore module-level IDNA hooks to their stdlib defaults."""
    mutable_url.configure_idna(
        encode=mutable_url._default_encode_host,
        decode=mutable_url._default_decode_host,
    )


@pytest.fixture(autouse=True)
def reset_idna():
    """Guarantee each test starts and ends with the default IDNA hooks."""
    _reset_idna_hooks()
    yield
    _reset_idna_hooks()


# ---------------------------------------------------------------------------
# Parsing and round-trip fidelity
# ---------------------------------------------------------------------------

class TestParsing:

    @pytest.mark.parametrize("url, field, expected", [
        ("https://example.com/path",            "scheme",   "https"),
        ("https://example.com/path",            "host",     "example.com"),
        ("https://example.com:8080/path",       "port",     8080),
        ("https://example.com/path?q=1",        "query",    "q=1"),
        ("https://example.com/path#sec",        "fragment", "sec"),
        ("https://example.com/a/b/c",           "path",     "/a/b/c"),
        ("https://user:pass@example.com/",      "auth",     "user:pass"),
        ("https://user@example.com/",           "auth",     "user"),
        # absent components come back as None
        ("https://example.com/",                "query",    None),
        ("https://example.com/",                "fragment", None),
        ("https://example.com/",                "auth",     None),
        ("https://example.com/",                "port",     None),
    ])
    def test_field(self, url, field, expected):
        assert getattr(MutableURL(url), field) == expected

    @pytest.mark.parametrize("url", [
        "https://example.com/",
        "https://example.com:8080/path?q=1#frag",
        "https://user:pass@example.com/",
        "http://example.com",
        "ftp://ftp.example.com/pub/file.tar.gz",
        "https://example.com/path%20with%20spaces",
    ])
    def test_roundtrip(self, url):
        """Parsing then stringifying should reproduce the original URL."""
        assert str(MutableURL(url)) == url


# ---------------------------------------------------------------------------
# Mutation of base fields
# ---------------------------------------------------------------------------

class TestMutation:

    @pytest.mark.parametrize("field, new_value, expected_url", [
        ("scheme",   "ftp",        "ftp://example.com/path"),
        ("host",     "other.com",  "https://other.com/path"),
        ("port",     9090,         "https://example.com:9090/path"),
        ("path",     "/new",       "https://example.com/new"),
        ("query",    "x=2",        "https://example.com/path?x=2"),
        ("fragment", "top",        "https://example.com/path#top"),
    ])
    def test_set_base_field(self, field, new_value, expected_url):
        u = MutableURL("https://example.com/path")
        setattr(u, field, new_value)
        assert str(u) == expected_url

    def test_mutations_compose(self):
        """Sequential mutations should each take effect independently."""
        u = MutableURL("https://example.com/")
        u.scheme = "http"
        u.host = "other.org"
        u.port = 8080
        u.path = "/api"
        u.query = "v=1"
        u.fragment = "anchor"
        assert str(u) == "http://other.org:8080/api?v=1#anchor"

    def test_set_field_to_none_removes_it(self):
        u = MutableURL("https://example.com/path?q=1#frag")
        u.query = None
        u.fragment = None
        assert str(u) == "https://example.com/path"


# ---------------------------------------------------------------------------
# netloc and request_uri
# ---------------------------------------------------------------------------

class TestComputedFields:

    @pytest.mark.parametrize("url, expected_netloc", [
        ("https://example.com/",            "example.com"),
        ("https://example.com:8080/",       "example.com:8080"),
        ("https://user:pass@example.com/",  "user:pass@example.com"),
        ("https://user@example.com:9000/",  "user@example.com:9000"),
    ])
    def test_netloc(self, url, expected_netloc):
        assert MutableURL(url).netloc == expected_netloc

    @pytest.mark.parametrize("url, expected_uri", [
        ("https://example.com/",            "/"),
        ("https://example.com/path",        "/path"),
        ("https://example.com/path?q=1",    "/path?q=1"),
        # no path but query — edge case
        # https://example.com?q=1 has no path component; HTTP requires '/'
        # so request_uri correctly becomes '/?q=1', not '?q=1'
        ("https://example.com?q=1",         "/?q=1"),

    ])
    def test_request_uri(self, url, expected_uri):
        assert MutableURL(url).request_uri == expected_uri


# ---------------------------------------------------------------------------
# username / password  — encoding and independence
# ---------------------------------------------------------------------------

class TestUserinfo:

    @pytest.mark.parametrize("url, expected_user, expected_pass", [
        ("https://user:pass@example.com/",            "user",     "pass"),
        ("https://user@example.com/",                 "user",     None),
        ("https://example.com/",                      None,       None),
        # percent-encoded credentials are decoded for the caller
        ("https://user%40corp:s3cr%3At@example.com/", "user@corp", "s3cr:t"),
    ])
    def test_get_username_password(self, url, expected_user, expected_pass):
        u = MutableURL(url)
        assert u.username == expected_user
        assert u.password == expected_pass

    @pytest.mark.parametrize("plain_user, expected_encoded", [
        ("alice",      "alice"),
        ("user@corp",  "user%40corp"),   # @ must be encoded in username
        ("u:name",     "u%3Aname"),      # : must be encoded in username
        ("héllo",      "h%C3%A9llo"),    # non-ASCII percent-encoded
    ])
    def test_set_username_encoding(self, plain_user, expected_encoded):
        u = MutableURL("https://example.com/")
        u.username = plain_user
        assert u.auth == expected_encoded

    @pytest.mark.parametrize("plain_pass, expected_encoded", [
        ("secret",      "secret"),
        ("p@ss",        "p%40ss"),       # @ must be encoded in password
        ("s3cr:t",      "s3cr:t"),       # : is allowed unencoded in password
        ("pàss",        "p%C3%A0ss"),    # non-ASCII percent-encoded
    ])
    def test_set_password_encoding(self, plain_pass, expected_encoded):
        u = MutableURL("https://user@example.com/")
        u.password = plain_pass
        assert u.auth == f"user:{expected_encoded}"

    def test_set_username_preserves_raw_password(self):
        """Changing username must not decode-and-re-encode the existing password."""
        # password contains a literal colon encoded as %3A
        u = MutableURL("https://old:s3cr%3At@example.com/")
        u.username = "new"
        # raw password must be exactly as parsed, not double-encoded
        assert u.auth == "new:s3cr%3At"

    def test_set_password_preserves_raw_username(self):
        """Changing password must not decode-and-re-encode the existing username."""
        u = MutableURL("https://user%40corp:old@example.com/")
        u.password = "newpass"
        assert u.auth == "user%40corp:newpass"

    def test_set_username_none_removes_user(self):
        u = MutableURL("https://user:pass@example.com/")
        u.username = None
        assert u.username is None
        assert u.password == "pass"
        assert u.auth == ":pass"

    def test_set_password_none_removes_password(self):
        u = MutableURL("https://user:pass@example.com/")
        u.password = None
        assert u.password is None
        assert u.username == "user"
        assert u.auth == "user"

    def test_set_both_none_clears_auth(self):
        u = MutableURL("https://user:pass@example.com/")
        u.password = None
        u.username = None
        assert u.auth is None
        assert "https://example.com/" == str(u)

    def test_credentials_survive_roundtrip_in_url(self):
        """Encoded credentials must appear verbatim in the reconstructed URL."""
        original = "https://user%40corp:s3cr%3At@example.com/"
        assert str(MutableURL(original)) == original


# ---------------------------------------------------------------------------
# hostname — IDNA / punycode with stdlib (IDNA2003)
# ---------------------------------------------------------------------------

class TestHostnameIDNA2003:
    """Tests using the default stdlib IDNA2003 hooks."""

    @pytest.mark.parametrize("unicode_host, expected_ace", [
        ("münchen.de",  "xn--mnchen-3ya.de"),
        ("例え.jp",     "xn--r8jz45g.jp"),
        ("ドメイン.テスト",  "xn--eckwd4c7c.xn--zckzah"),  # two non-ASCII labels
        ("example.com", "example.com"),  # pure ASCII — no change
    ])
    def test_set_hostname_encodes_to_ace(self, unicode_host, expected_ace):
        u = MutableURL("https://example.com/")
        u.hostname = unicode_host
        assert u.host == expected_ace

    @pytest.mark.parametrize("ace_host, expected_unicode", [
        ("xn--mnchen-3ya.de",                       "münchen.de"),
        ("xn--r8jz45g.jp",                          "例え.jp"),
        ("xn--eckwd4c7c.xn--zckzah",                "ドメイン.テスト"),
        ("example.com",                             "example.com"),
    ])
    def test_get_hostname_decodes_to_unicode(self, ace_host, expected_unicode):
        u = MutableURL(f"https://{ace_host}/")
        assert u.hostname == expected_unicode

    @pytest.mark.parametrize("ip_literal", [
        "192.168.1.1",
        "[::1]",
        "[2001:db8::1]",
    ])
    def test_ip_literals_pass_through_unchanged(self, ip_literal):
        u = MutableURL(f"https://{ip_literal}/")
        assert u.host == ip_literal
        assert u.hostname == ip_literal

    def test_hostname_set_unicode_roundtrips(self):
        u = MutableURL("https://placeholder.com/path?q=1")
        u.hostname = "münchen.de"
        # host holds ACE, hostname decodes it back
        assert u.hostname == "münchen.de"
        assert u.host    == "xn--mnchen-3ya.de"
        assert str(u)    == "https://xn--mnchen-3ya.de/path?q=1"

    # --- IDNA2003 vs IDNA2008 behavioural difference ---
    #
    # 'faß.de' is the canonical example:
    #   IDNA2003 (stdlib): ß is case-folded to 'ss' → stored as 'fass.de'
    #   IDNA2008 (idna pkg): ß is a valid character → stored as 'xn--fa-hia.de'
    #
    def test_sharp_s_idna2003_folds_to_ss(self):
        u = MutableURL("https://example.com/")
        u.hostname = "faß.de"
        # stdlib IDNA2003 maps ß→ss; result is plain ASCII, no xn-- prefix
        assert u.host == "fass.de"

    def test_parse_unicode_host_encoded_at_parse_time(self):
        """A unicode host supplied in the URL string is encoded during parsing."""
        # urllib.parse.urlsplit does accept unicode input
        u = MutableURL("https://münchen.de/path")
        assert u.host     == "xn--mnchen-3ya.de"
        assert u.hostname == "münchen.de"


# ---------------------------------------------------------------------------
# configure_idna() hook
# ---------------------------------------------------------------------------

class TestConfigureIdna:
    """Tests for the module-level IDNA hook mechanism."""

    def test_configure_idna_affects_encode(self):
        sentinel = {}

        def fake_encode(host):
            sentinel['called_with'] = host
            return "fake-encoded.example"

        mutable_url.configure_idna(encode=fake_encode, decode=mutable_url._default_decode_host)
        u = MutableURL("https://example.com/")
        u.hostname = "münchen.de"

        assert sentinel['called_with'] == "münchen.de"
        assert u.host == "fake-encoded.example"

    def test_configure_idna_affects_decode(self):
        sentinel = {}

        def fake_decode(host):
            sentinel['called_with'] = host
            return "fake-decoded.example"

        mutable_url.configure_idna(encode=mutable_url._default_encode_host, decode=fake_decode)
        u = MutableURL("https://xn--mnchen-3ya.de/")
        result = u.hostname

        assert sentinel['called_with'] == "xn--mnchen-3ya.de"
        assert result == "fake-decoded.example"

    def test_configure_idna_affects_parse_time_encode(self):
        """Hooks must be consulted when parsing a URL, not just on property access."""
        calls = []

        def recording_encode(host):
            calls.append(host)
            return mutable_url._default_encode_host(host)

        mutable_url.configure_idna(encode=recording_encode, decode=mutable_url._default_decode_host)
        MutableURL("https://münchen.de/")
        assert any("münchen" in (c or "") for c in calls)

    def test_reset_to_defaults_restores_behaviour(self):
        mutable_url.configure_idna(
            encode=lambda h: "broken",
            decode=lambda h: "broken",
        )
        _reset_idna_hooks()
        u = MutableURL("https://example.com/")
        u.hostname = "münchen.de"
        assert u.host == "xn--mnchen-3ya.de"

    # --- IDNA2008 via the real 'idna' package (skipped if not installed) ---

    @pytest.fixture
    def idna2008_hooks(self):
        idna = pytest.importorskip("idna")

        def enc(host):
            if host is None or mutable_url._is_ip_literal(host):
                return host
            try:
                return idna.encode(host).decode('ascii')  # returns ACE by default
            except (idna.IDNAError, UnicodeError):
                return host

        def dec(host):
            if host is None or mutable_url._is_ip_literal(host):
                return host
            try:
                return idna.decode(host)
            except (idna.IDNAError, UnicodeError):
                return host

        mutable_url.configure_idna(encode=enc, decode=dec)
        yield idna

    def test_sharp_s_idna2008_preserves_as_punycode(self, idna2008_hooks):
        u = MutableURL("https://example.com/")
        u.hostname = "faß.de"
        assert u.host == "xn--fa-hia.de"

    def test_sharp_s_idna2003_vs_idna2008_differ(self, idna2008_hooks):
        u_2008 = MutableURL("https://example.com/")
        u_2008.hostname = "faß.de"
        ace_2008 = u_2008.host

        _reset_idna_hooks()

        u_2003 = MutableURL("https://example.com/")
        u_2003.hostname = "faß.de"
        ace_2003 = u_2003.host

        assert ace_2003 == "fass.de"
        assert ace_2008 == "xn--fa-hia.de"
        assert ace_2003 != ace_2008

    def test_emoji_domain_idna2008_fallback(self, idna2008_hooks):
        """IDNA2008 expressly prohibits emoji; hook falls back to original."""
        u = MutableURL("https://example.com/")
        u.hostname = "☃.com"
        assert u.host == "☃.com"

    def test_emoji_domain_idna2003_encodes_snowman(self):
        """stdlib IDNA2003 is more permissive than IDNA2008: encodes the snowman."""
        u = MutableURL("https://example.com/")
        u.hostname = "☃.com"
        assert u.host == "xn--n3h.com"


# ---------------------------------------------------------------------------
# query_params / query_params_list / query_params_multi
# ---------------------------------------------------------------------------

class TestQueryParams:

    # -- parsing: None vs "" distinction -------------------------------------

    @pytest.mark.parametrize("url, expected_list", [
        # typical key=value
        ("https://example.com/?q=hello",
         [("q", "hello")]),
        # valueless param (no '=' sign) → None
        ("https://example.com/?flag",
         [("flag", None)]),
        # '=' present but empty value → ""
        ("https://example.com/?x=",
         [("x", "")]),
        # mix of all three forms
        ("https://example.com/?a=1&flag&empty=",
         [("a", "1"), ("flag", None), ("empty", "")]),
        # no query string at all
        ("https://example.com/",
         []),
        # empty query string (bare '?')
        ("https://example.com/?",
         []),
    ])
    def test_query_params_list_basic(self, url, expected_list):
        assert MutableURL(url).query_params_list == expected_list

    # -- repeated keys -------------------------------------------------------

    def test_repeated_keys_query_params_list_preserves_all(self):
        u = MutableURL("https://example.com/?color=red&color=blue&lang=en")
        assert u.query_params_list == [
            ("color", "red"), ("color", "blue"), ("lang", "en"),
        ]

    def test_repeated_keys_query_params_last_wins(self):
        u = MutableURL("https://example.com/?color=red&color=blue&lang=en")
        assert u.query_params == {"color": "blue", "lang": "en"}

    def test_repeated_keys_query_params_multi(self):
        u = MutableURL("https://example.com/?color=red&color=blue&lang=en")
        assert u.query_params_multi == {"color": ["red", "blue"], "lang": ["en"]}

    def test_repeated_key_with_none_value_in_multi(self):
        u = MutableURL("https://example.com/?flag&flag=yes")
        assert u.query_params_multi == {"flag": [None, "yes"]}

    # -- decoding: unquote_plus ----------------------------------------------

    def test_percent_encoded_key_and_value_decoded(self):
        u = MutableURL("https://example.com/?hel%20lo=wor%20ld")
        assert u.query_params == {"hel lo": "wor ld"}

    def test_plus_decoded_as_space(self):
        u = MutableURL("https://example.com/?q=hello+world&name=foo+bar")
        assert u.query_params == {"q": "hello world", "name": "foo bar"}

    def test_percent_encoded_plus_stays_as_plus(self):
        # %2B in the raw query is a literal '+', not a space
        u = MutableURL("https://example.com/?sym=%2B")
        assert u.query_params == {"sym": "+"}

    def test_unicode_percent_encoded_decoded(self):
        u = MutableURL("https://example.com/?city=M%C3%BCnchen")
        assert u.query_params == {"city": "München"}

    # -- writing via query_params (dict) -------------------------------------

    def test_set_query_params_dict_simple(self):
        u = MutableURL("https://example.com/")
        u.query_params = {"x": "hello world", "y": "1"}
        assert u.query_params == {"x": "hello world", "y": "1"}

    def test_set_query_params_dict_none_value_no_equals(self):
        u = MutableURL("https://example.com/")
        u.query_params = {"flag": None}
        assert u.query == "flag"

    def test_set_query_params_dict_empty_string_value_has_equals(self):
        u = MutableURL("https://example.com/")
        u.query_params = {"x": ""}
        assert u.query == "x="

    def test_set_query_params_dict_spaces_encoded_as_plus(self):
        u = MutableURL("https://example.com/")
        u.query_params = {"q": "hello world"}
        assert u.query == "q=hello+world"

    def test_set_query_params_dict_empty_clears_query(self):
        u = MutableURL("https://example.com/?q=1")
        u.query_params = {}
        assert u.query is None

    def test_set_query_params_dict_replaces_all(self):
        u = MutableURL("https://example.com/?old=gone")
        u.query_params = {"new": "here"}
        assert u.query_params == {"new": "here"}

    # -- writing via query_params_list ---------------------------------------

    def test_set_query_params_list_preserves_order_and_repeats(self):
        u = MutableURL("https://example.com/")
        u.query_params_list = [("color", "red"), ("color", "blue"), ("flag", None)]
        assert u.query_params_list == [("color", "red"), ("color", "blue"), ("flag", None)]

    def test_set_query_params_list_empty_clears_query(self):
        u = MutableURL("https://example.com/?q=1")
        u.query_params_list = []
        assert u.query is None

    def test_set_query_params_list_none_value_no_equals_sign(self):
        u = MutableURL("https://example.com/")
        u.query_params_list = [("flag", None), ("x", "1")]
        assert u.query == "flag&x=1"

    def test_set_query_params_list_empty_string_value_has_equals(self):
        u = MutableURL("https://example.com/")
        u.query_params_list = [("x", ""), ("y", "2")]
        assert u.query == "x=&y=2"

    # -- round-trips ---------------------------------------------------------

    def test_dict_roundtrip(self):
        u = MutableURL("https://example.com/")
        original = {"q": "hello world", "lang": "en", "flag": None, "empty": ""}
        u.query_params = original
        assert u.query_params == original

    def test_list_roundtrip(self):
        u = MutableURL("https://example.com/")
        original = [("color", "red"), ("color", "blue"), ("flag", None), ("x", "")]
        u.query_params_list = original
        assert u.query_params_list == original

    def test_query_params_does_not_affect_other_fields(self):
        u = MutableURL("https://user:pass@example.com:8080/path#frag")
        u.query_params = {"k": "v"}
        assert u.scheme   == "https"
        assert u.username == "user"
        assert u.password == "pass"
        assert u.host     == "example.com"
        assert u.port     == 8080
        assert u.path     == "/path"
        assert u.fragment == "frag"

    # -- subscript assignment via query_params[key] = value -----------------

    def test_subscript_assign_no_params_yet(self):
        """Subscript assignment works when the URL has no query string at all."""
        u = MutableURL("https://example.com/")
        assert u.query is None
        u.query_params['x'] = 'hello'
        assert u.query_params == {'x': 'hello'}
        assert u.query == 'x=hello'

    def test_subscript_assign_new_param(self):
        """Subscript assignment adds a key that does not yet exist."""
        u = MutableURL("https://example.com/?existing=1")
        u.query_params['new'] = 'added'
        assert u.query_params == {'existing': '1', 'new': 'added'}

    def test_subscript_assign_change_param(self):
        """Subscript assignment updates an existing key."""
        u = MutableURL("https://example.com/?x=old")
        u.query_params['x'] = 'new'
        assert u.query_params == {'x': 'new'}

    def test_subscript_assign_int_coerced_to_str(self):
        """Non-string values are coerced to str; u.query_params['foo'] = 3 must work."""
        # TODO: determine if we wish to relax the typing to allow this somehow,
        # while still preserving the invariant that what we allow _out_ is guaranteed to
        # be a str and callers do not need to handle the types: we fixed the type on the way in.
        u = MutableURL("https://example.com/")
        u.query_params['foo'] = 3  # ty: ignore[invalid-assignment]
        assert u.query_params == {'foo': '3'}

    def test_subscript_assign_none_produces_valueless_param(self):
        """Assigning None via subscript produces a key-only (no '=') parameter."""
        u = MutableURL("https://example.com/")
        u.query_params['flag'] = None
        assert u.query == 'flag'
        assert u.query_params == {'flag': None}

    # -- query_params_multi is read-only -------------------------------------

    def test_query_params_multi_has_no_setter(self):
        u = MutableURL("https://example.com/")
        with pytest.raises(AttributeError):
            u.query_params_multi = {"k": ["v"]}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MutableURL.from_parts
# ---------------------------------------------------------------------------

class TestFromParts:

    def test_basic_construction(self):
        u = MutableURL.from_parts(scheme="https", host="example.com", path="/api")
        assert str(u) == "https://example.com/api"

    def test_all_base_fields(self):
        u = MutableURL.from_parts(
            scheme="https", host="example.com", port=8080,
            path="/path", query="q=1", fragment="sec",
        )
        assert str(u) == "https://example.com:8080/path?q=1#sec"

    def test_all_none_produces_empty_url(self):
        u = MutableURL.from_parts()
        assert str(u) == ""

    def test_result_is_mutable(self):
        u = MutableURL.from_parts(scheme="https", host="example.com", path="/")
        u.port = 8080
        assert str(u) == "https://example.com:8080/"

    # -- host / hostname mutual exclusion -------------------------------------

    def test_hostname_idna_encoded(self):
        u = MutableURL.from_parts(scheme="https", hostname="münchen.de", path="/")
        assert u.host == "xn--mnchen-3ya.de"
        assert u.hostname == "münchen.de"

    def test_host_and_hostname_mutually_exclusive(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            MutableURL.from_parts(host="example.com", hostname="example.com")

    # -- auth / username / password mutual exclusion --------------------------

    def test_username_and_password(self):
        u = MutableURL.from_parts(
            scheme="https", host="example.com",
            username="user", password="pass", path="/",
        )
        assert u.username == "user"
        assert u.password == "pass"
        assert str(u) == "https://user:pass@example.com/"

    def test_username_only(self):
        u = MutableURL.from_parts(scheme="https", host="example.com", username="user", path="/")
        assert u.username == "user"
        assert u.password is None
        assert u.auth == "user"

    def test_password_without_username_bearer_token(self):
        """password-only auth produces ':token' userinfo, the form used by bearer-style REST APIs."""
        u = MutableURL.from_parts(
            scheme="https", host="api.example.com",
            password="mytoken", path="/v1/data",
        )
        assert u.username is None
        assert u.password == "mytoken"
        assert u.auth == ":mytoken"

    def test_username_percent_encoded(self):
        u = MutableURL.from_parts(scheme="https", host="example.com", username="user@corp", path="/")
        assert u.auth == "user%40corp"

    def test_password_colon_allowed_unencoded(self):
        u = MutableURL.from_parts(
            scheme="https", host="example.com",
            username="user", password="s3cr:t", path="/",
        )
        assert u.auth == "user:s3cr:t"

    def test_raw_auth_stored_verbatim(self):
        u = MutableURL.from_parts(
            scheme="https", host="example.com",
            auth="user%40corp:s3cr%3At", path="/",
        )
        assert u.username == "user@corp"
        assert u.password == "s3cr:t"

    def test_auth_mutually_exclusive_with_username(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            MutableURL.from_parts(auth="user:pass", username="user")

    def test_auth_mutually_exclusive_with_password(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            MutableURL.from_parts(auth="user:pass", password="pass")

    # -- query / query_params / query_params_list mutual exclusion ------------

    def test_raw_query(self):
        u = MutableURL.from_parts(scheme="https", host="example.com", path="/", query="q=1&flag")
        assert u.query == "q=1&flag"

    def test_query_params_dict(self):
        u = MutableURL.from_parts(
            scheme="https", host="example.com", path="/",
            query_params={"q": "hello world", "lang": "en"},
        )
        assert u.query_params == {"q": "hello world", "lang": "en"}

    def test_query_params_dict_empty_omits_query(self):
        u = MutableURL.from_parts(
            scheme="https", host="example.com", path="/", query_params={},
        )
        assert u.query is None

    def test_query_params_list_preserves_order_and_repeats(self):
        u = MutableURL.from_parts(
            scheme="https", host="example.com", path="/",
            query_params_list=[("color", "red"), ("color", "blue"), ("flag", None)],
        )
        assert u.query_params_list == [("color", "red"), ("color", "blue"), ("flag", None)]

    def test_query_params_list_empty_omits_query(self):
        u = MutableURL.from_parts(
            scheme="https", host="example.com", path="/", query_params_list=[],
        )
        assert u.query is None

    def test_query_and_query_params_mutually_exclusive(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            MutableURL.from_parts(query="q=1", query_params={"q": "1"})

    def test_query_and_query_params_list_mutually_exclusive(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            MutableURL.from_parts(query="q=1", query_params_list=[("q", "1")])

    def test_query_params_and_query_params_list_mutually_exclusive(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            MutableURL.from_parts(query_params={"q": "1"}, query_params_list=[("q", "1")])

    # -- equivalence with parse -----------------------------------------------

    def test_from_parts_matches_parse(self):
        """from_parts must produce the same URL string as parsing an equivalent URL."""
        url_str = "https://user:pass@example.com:443/path?q=hello+world#section"
        parsed = MutableURL(url_str)
        built = MutableURL.from_parts(
            scheme="https", username="user", password="pass",
            host="example.com", port=443, path="/path",
            query_params={"q": "hello world"}, fragment="section",
        )
        assert str(parsed) == str(built)

    def test_eq_init_vs_from_parts(self):
        """Objects constructed via __init__ and from_parts compare equal when equivalent."""
        url_str = "https://user:pass@example.com:443/path?q=hello+world#section"
        parsed = MutableURL(url_str)
        built = MutableURL.from_parts(
            scheme="https", username="user", password="pass",
            host="example.com", port=443, path="/path",
            query_params={"q": "hello world"}, fragment="section",
        )
        assert parsed == built

    def test_eq_reflexive(self):
        u = MutableURL("https://example.com/path?q=1")
        assert u == u

    def test_eq_different_urls_not_equal(self):
        assert MutableURL("https://example.com/") != MutableURL("https://other.com/")


# ---------------------------------------------------------------------------
# __all__ and public surface
# ---------------------------------------------------------------------------

class TestPublicSurface:

    def test_mutableurl_exported(self):
        assert "MutableURL" in mutable_url.__all__

    def test_configure_idna_exported(self):
        assert "configure_idna" in mutable_url.__all__


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
