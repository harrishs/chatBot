import axios from "axios";
import { getCSRFToken } from "../utils/csrf.js";

let csrfTokenGetter = getCSRFToken;

export function __setCSRFTokenGetter(getter) {
        csrfTokenGetter = typeof getter === "function" ? getter : getCSRFToken;
}

export function __resetCSRFTokenGetter() {
        csrfTokenGetter = getCSRFToken;
}

const baseURL = import.meta.env?.VITE_API_BASE_URL || "/api";

const api = axios.create({
	baseURL,
	withCredentials: true,
	xsrfCookieName: "csrftoken",
	xsrfHeaderName: "X-CSRFToken",
});

api.interceptors.request.use((config) => {
        const headers = config.headers ?? (config.headers = {});
        if (!headers["X-CSRFToken"]) {
                const token = csrfTokenGetter();
                if (token) {
                        headers["X-CSRFToken"] = token;
                }
        }
	return config;
});

export default api;
