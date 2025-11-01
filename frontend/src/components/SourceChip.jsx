import PropTypes from "prop-types";

const baseStyle = {
        display: "inline-flex",
        alignItems: "center",
        gap: "0.5rem",
        padding: "0.35rem 0.65rem",
        borderRadius: "999px",
        backgroundColor: "#eef2ff",
        border: "1px solid #c7d2fe",
        color: "#312e81",
        fontSize: "0.85rem",
        lineHeight: 1.2,
        textDecoration: "none",
};

const linkStyle = {
        color: "#4338ca",
        fontWeight: 600,
        textDecoration: "underline",
};

function SourceChip({ source }) {
        if (!source) {
                return null;
        }

        const label =
                source.source_display ||
                source.title ||
                source.source_id ||
                source.source ||
                "Source";

        return (
                <span className="source-chip" style={baseStyle}>
                        <span>{label}</span>
                        {source.source_url ? (
                                <a
                                        href={source.source_url}
                                        target="_blank"
                                        rel="noreferrer"
                                        style={linkStyle}
                                >
                                        View source
                                </a>
                        ) : null}
                </span>
        );
}

SourceChip.propTypes = {
        source: PropTypes.shape({
                source_display: PropTypes.string,
                title: PropTypes.string,
                source_id: PropTypes.string,
                source: PropTypes.string,
                source_url: PropTypes.string,
        }),
};

export default SourceChip;
