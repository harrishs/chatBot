import test, { mock } from "node:test";
import assert from "node:assert/strict";

test("request interceptor sets CSRF header once", async (t) => {
        const token = "csrf-token";
        let callCount = 0;

        mock.module(new URL("../src/utils/csrf.js", import.meta.url), {
                namedExports: {
                        getCSRFToken: () => {
                                callCount += 1;
                                return token;
                        },
                },
        });

        t.after(() => {
                mock.restoreAll();
        });

        const { default: api } = await import("../src/api/axios.js");

        const handler = api.interceptors.request.handlers.find(Boolean);

        assert.ok(handler, "expected request interceptor to be registered");

        const config = { headers: {} };

        await handler.fulfilled(config);
        await handler.fulfilled(config);

        assert.equal(callCount, 1);
        assert.equal(config.headers["X-CSRFToken"], token);
});
