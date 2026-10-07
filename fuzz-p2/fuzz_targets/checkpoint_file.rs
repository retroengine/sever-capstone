//! §14.2 paged files and §14.9 checkpoint streams: never panic; a parsed image re-serialises to
//! the same streams.
#![no_main]

use libfuzzer_sys::fuzz_target;
use sever_format::image::CheckpointStreams;
use sever_format::{DbImage, Layout, magic, paged};

fuzz_target!(|data: &[u8]| {
    if let Ok((seq, s)) = paged::decode(data, &magic::SLOTS, 0) {
        assert_eq!(paged::encode(&magic::SLOTS, 0, seq, &s), data);
    }
    // Split the input into the six streams by its first bytes.
    if data.len() < 6 {
        return;
    }
    let cuts: Vec<usize> = data[..6].iter().map(|&b| b as usize).collect();
    let mut rest = &data[6..];
    let mut take = |n: usize| {
        let n = n.min(rest.len());
        let (a, b) = rest.split_at(n);
        rest = b;
        a.to_vec()
    };
    let streams = CheckpointStreams {
        meta: take(cuts[0] * 4),
        collections: take(cuts[1] * 2),
        groups: take(cuts[2] * 8),
        slots: take(cuts[3] * 8),
        locator: take(cuts[4] * 4),
        payload_refs: take(cuts[5] * 2),
        artefacts: Vec::new(),
    };
    let layout = |_: &sever_format::CollectionMeta| Layout::plain(8);
    if let Ok((meta, img)) = DbImage::from_streams(&streams, &layout) {
        let again = img.to_streams(&meta, &layout).expect("an accepted image serialises");
        assert_eq!(again.meta, streams.meta);
        assert_eq!(again.groups, streams.groups);
        assert_eq!(again.slots, streams.slots);
        assert_eq!(again.locator, streams.locator);
    }
});
