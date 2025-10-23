export function getCookieValue(
	name,
	cookieString = typeof document !== "undefined" ? document.cookie : ""
) {
	if (!name || !cookieString) {
		return null;
	}

	return cookieString
		.split(";")
		.map((cookie) => cookie.trim())
		.filter(Boolean)
		.reduce((acc, cookie) => {
			if (acc !== null) {
				return acc;
			}
			const [key, ...valueParts] = cookie.split("=");
			if (key === name) {
				return decodeURIComponent(valueParts.join("="));
			}
			return null;
		}, null);
}

export function getCSRFToken() {
	return getCookieValue("csrftoken");
}
