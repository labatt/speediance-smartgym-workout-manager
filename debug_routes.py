from flask import Blueprint, render_template, request, jsonify, redirect, url_for

debug_bp = Blueprint('debug', __name__)
_client = None


def init_debug(client):
    """Register the shared API client with this blueprint."""
    global _client
    _client = client
    return debug_bp


@debug_bp.route('/debug')
def debug_console():
    if not _client.credentials.get("token"):
        return redirect(url_for('settings'))
    return render_template('debug_console.html', base_url=_client.base_url)


@debug_bp.route('/debug/proxy', methods=['POST'])
def debug_proxy():
    if not _client.credentials.get("token"):
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json()
    method = (data.get('method') or 'GET').upper()
    url = (data.get('url') or '').strip()
    use_auth = data.get('useAuthHeaders', True)
    extra_headers = data.get('headers') or {}
    body_mode = data.get('bodyMode', 'none')
    json_body = data.get('jsonBody')
    raw_body = data.get('rawBody')

    # Prepend base URL if only a path was given
    if url.startswith('/'):
        url = _client.base_url + url

    headers = {}
    if use_auth:
        headers.update(_client._get_headers())
    headers.update(extra_headers)

    kwargs = {'headers': headers}
    if body_mode == 'json' and json_body is not None:
        kwargs['json'] = json_body
    elif body_mode == 'raw' and raw_body:
        kwargs['data'] = raw_body

    try:
        resp = _client._request(method, url, **kwargs)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return jsonify({"status": resp.status_code, "headers": dict(resp.headers), "body": body})
    except Exception as e:
        return jsonify({"error": str(e), "debug": _client.last_debug_info})
