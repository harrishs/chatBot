import PropTypes from "prop-types";

function ConfidenceBadge({ confidence }) {
        if (typeof confidence !== "number" || Number.isNaN(confidence)) {
                return null;
        }

        const bounded = Math.max(0, Math.min(confidence, 1));
        const percentage = Math.round(bounded * 100);

        return (
                <div className="confidence-badge" aria-label={`Confidence ${percentage}%`}>
                        <span className="confidence-label">Confidence: {percentage}%</span>
                        <div className="confidence-meter" role="presentation">
                                <div
                                        className="confidence-meter__fill"
                                        style={{ width: `${percentage}%` }}
                                />
                        </div>
                </div>
        );
}

ConfidenceBadge.propTypes = {
        confidence: PropTypes.number,
};

export default ConfidenceBadge;
