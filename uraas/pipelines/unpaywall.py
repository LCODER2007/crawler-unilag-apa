import requests


class UnpaywallPipeline:
    """Verifies legal Open Access PDF bitstreams via Unpaywall before ingestion."""

    def process_item(self, item, spider):
        doi = item.get("doi")
        if not doi:
            return item

        # Already have a PDF? Unpaywall might find a better/legal one, but let's check
        try:
            # Unpaywall requires an email for the API
            url = f"https://api.unpaywall.org/v2/{doi}?email=uraas-bot@unilag.edu.ng"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                is_oa = data.get("is_oa", False)
                oa_status = data.get("oa_status", "closed")
                item["oa_status"] = oa_status

                # Smart Version Detection
                if oa_status in ["gold", "hybrid", "green"]:
                    item["suggested_access"] = "Public"  # Safe to share
                else:
                    item["suggested_access"] = "Private"  # Restricted/Bronze/Closed

                if is_oa and data.get("best_oa_location"):
                    legal_pdf = data["best_oa_location"].get("url_for_pdf")
                    if legal_pdf:
                        item["pdf_url"] = legal_pdf
                        spider.logger.info(
                            f"Unpaywall ({oa_status}): Found legal PDF for {doi}"
                        )
        except Exception as e:
            spider.logger.debug(f"Unpaywall check failed for {doi}: {e}")

        return item
