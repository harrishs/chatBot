function normalizeConfidence(value) {
        if (value === null || value === undefined) {
                return null;
        }

        if (typeof value === "string") {
                const numeric = parseFloat(value.replace(/[^0-9.]/g, ""));
                if (Number.isNaN(numeric)) {
                        return null;
                }
                return Math.max(0, Math.min(100, numeric > 1 ? numeric : numeric * 100));
        }

        if (typeof value === "number" && Number.isFinite(value)) {
                const scaled = value <= 1 ? value * 100 : value;
                return Math.max(0, Math.min(100, scaled));
        }

        return null;
}

function describeConfidence(percentage) {
        if (percentage === null) {
                return "";
        }

        if (percentage >= 75) {
                return "High";
        }
        if (percentage >= 50) {
                return "Medium";
        }
        if (percentage > 0) {
                return "Low";
        }
        return "Unknown";
}

function ConfidenceBadge({ confidence = null }) {
        const percentage = normalizeConfidence(confidence);

        if (percentage === null) {
                return null;
        }

        const description = describeConfidence(percentage);

        return (
                <div className="chatbot-confidence" role="status" aria-live="polite">
                        <div className="chatbot-confidence__label">
                                Confidence: {description} ({Math.round(percentage)}%)
                        </div>
                        <div className="chatbot-confidence__meter" aria-hidden="true">
                                <div
                                        className="chatbot-confidence__meter-fill"
                                        style={{ width: `${percentage}%` }}
                                />
                        </div>
                </div>
        );
}

export default ConfidenceBadge;
