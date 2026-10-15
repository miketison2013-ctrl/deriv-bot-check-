
    def _request(self, ws, payload):
        req_id = payload.get("req_id")

        try:
            ws.send(json.dumps(payload))

            while True:
                raw = ws.recv()

                if not raw:
                    raise DerivAPIError(
                        "Deriv closed the WebSocket connection "
                        "before returning a response."
                    )

                try:
                    response = json.loads(raw)
                except (TypeError, ValueError) as exc:
                    raise DerivAPIError(
                        "Deriv returned an unreadable response."
                    ) from exc

                if not isinstance(response, dict):
                    continue

                if response.get("error"):
                    error = response["error"]

                    if isinstance(error, dict):
                        code = error.get("code", "UnknownError")
                        message = error.get(
                            "message", "Deriv API error"
                        )
                        details = error.get("details")
                    else:
                        code = "UnknownError"
                        message = str(error)
                        details = None

                    diagnostic = (
                        f"Deriv API error [{code}]: {message}"
                    )

                    if details:
                        diagnostic += f" | Details: {details}"

                    diagnostic += (
                        f" | Request type: "
                        f"{next(iter(payload), 'unknown')}"
                    )

                    raise DerivAPIError(diagnostic)

                if (
                    req_id is None
                    or response.get("req_id") == req_id
                ):
                    return response

        except DerivAPIError:
            raise
        except Exception as exc:
            raise DerivAPIError(
                "WebSocket request failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
