import axios from "axios";
import { getCSRFToken } from "../utils/csrf";

const baseURL = import.meta.env?.VITE_API_BASE_URL || "/api";

const api = axios.create({
	baseURL,
	withCredentials: true,
	xsrfCookieName: "csrftoken",
	xsrfHeaderName: "X-CSRFToken",
});

api.interceptors.request.use((config) => {
	const headers = config.headers ?? (config.headers = {});
	if (!headers["X-CSFRToken"]) {
		const token = getCSRFToken();
		if (token) {
			headers["X-CSRFToken"] = token;
		}
	}
	return config;
});

export default api;
