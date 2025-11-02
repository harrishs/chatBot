import test from "node:test";
import assert from "node:assert/strict";
import api, {
        __setCSRFTokenGetter,
        __resetCSRFTokenGetter,
} from "../src/api/axios.js";

test("request interceptor attaches CSRF header once", (t) => {
        const token = "stubbed-token";
        let calls = 0;

        __setCSRFTokenGetter(() => {
                calls += 1;
                return token;
        });

        t.after(() => {
                __resetCSRFTokenGetter();
        });

        const [handler] = api.interceptors.request.handlers;

        assert.ok(handler?.fulfilled, "request interceptor should register a fulfilled handler");

        const config = { headers: {} };
        handler.fulfilled(config);

        assert.equal(
                config.headers["X-CSRFToken"],
                token,
                "interceptor should set the CSRF header when missing",
        );

        handler.fulfilled(config);

        assert.equal(calls, 1, "CSRF token should only be fetched once when header already exists");
});
