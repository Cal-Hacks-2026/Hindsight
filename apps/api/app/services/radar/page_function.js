// Cheerio Scraper pageFunction (Apify Store actor apify/cheerio-scraper).
// Returns raw material only; app/services/radar/normalize.py turns it into §8.3 items,
// so all parsing stays in Python where it's unit-tested.
async function pageFunction(context) {
    const { request, $, json, body, contentType } = context;
    const out = {
        url: request.url,
        loadedUrl: request.loadedUrl,
        sourceId: request.userData.sourceId,
        campus: request.userData.campus,
        contentType: (contentType && contentType.type) || '',
    };
    if (json) {
        out.json = json;
    } else if (out.contentType.includes('xml')) {
        out.text = typeof body === 'string' ? body : body.toString('utf8');
    } else {
        out.jsonLd = $('script[type="application/ld+json"]').map((i, el) => $(el).text()).get();
        const selector = request.userData.jsonSelector;
        if (selector) out.embeddedJson = $(selector).map((i, el) => $(el).text()).get();
    }
    return out;
}
