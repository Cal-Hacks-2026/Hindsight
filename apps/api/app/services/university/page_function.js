// Cheerio Scraper pageFunction (Apify Store actor apify/cheerio-scraper) for guide pages.
// Returns the page's readable text only, one block per line; Python decides what to keep.
async function pageFunction(context) {
    const { request, response, $ } = context;
    $('script, style, noscript, svg, iframe, form, nav, header, footer').remove();
    const root = $('main').length ? $('main').first() : $('body');
    // A line break before every block element, so paragraphs and list items stay separate.
    root.find('h1, h2, h3, h4, h5, h6, p, li, dt, dd, tr, br, div, section').each((i, el) => {
        $(el).prepend('\n');
    });
    const text = root.text()
        .split('\n')
        .map((line) => line.replace(/\s+/g, ' ').trim())
        .filter(Boolean)
        .join('\n');
    return {
        sourceId: request.userData.sourceId,
        url: request.url,
        loadedUrl: request.loadedUrl,
        status: response ? response.status : null,
        title: $('title').first().text().trim(),
        text: text.slice(0, 40000),
    };
}
