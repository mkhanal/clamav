#![forbid(unsafe_code)]
#![allow(
    clippy::expect_used,
    clippy::panic,
    reason = "a sample generator stops loudly when it cannot write a sample"
)]

#[allow(
    dead_code,
    reason = "the generator uses only part of the shared fixtures"
)]
mod canary;
#[allow(
    dead_code,
    reason = "the generator uses only part of the shared fixtures"
)]
mod documents;

use std::{fs, path::PathBuf};

use canary::CANARY;

const WORD_MAIN: &str =
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml";
const MAIL_ONLY_MEMBER: &str = "word/metariki_mail_only_0001.txt";
const IMAGE_COUNT: usize = 12;
const IMAGE_BYTES: usize = 512 * 1024;
const DATASET_ROWS: usize = 400_000;
const NESTING_LEVELS: usize = 3;

fn word_with(parts: &[(&str, &[u8])]) -> Vec<u8> {
    documents::word_package(WORD_MAIN, &documents::word_body("quarterly figures"), parts)
}

fn main() {
    let output = PathBuf::from(
        std::env::args_os()
            .nth(1)
            .expect("usage: benchmark_samples <output directory>"),
    );
    fs::create_dir_all(&output).expect("the output directory");

    let image_names: Vec<String> = (0..IMAGE_COUNT)
        .map(|index| format!("word/media/image{index}.bin"))
        .collect();
    let images: Vec<Vec<u8>> = (0..IMAGE_COUNT)
        .map(|_| documents::pseudo_random_bytes(IMAGE_BYTES))
        .collect();
    let image_parts: Vec<(&str, &[u8])> = image_names
        .iter()
        .zip(&images)
        .map(|(name, bytes)| (name.as_str(), bytes.as_slice()))
        .collect();
    let report = word_with(&image_parts);
    let mail_only = word_with(&[(MAIL_ONLY_MEMBER, b"figures\n".as_slice())]);
    let mail_only_archive = documents::zip_archive(&[(MAIL_ONLY_MEMBER, b"figures\n".as_slice())]);
    let canary_document = word_with(&[("word/notes.txt", CANARY.as_bytes())]);
    let mut nested = report.clone();
    for level in 0..NESTING_LEVELS {
        let name = format!("level{level}.docx");
        nested = documents::zip_archive(&[(name.as_str(), nested.as_slice())]);
    }

    let dataset: Vec<u8> = (0..DATASET_ROWS)
        .flat_map(|row| {
            format!(
                "{row},SITE-{:03},B{:07},{}.{:03},mg/L\n",
                row % 300,
                row * 7919 % 10_000_000,
                row % 9973,
                row % 1000
            )
            .into_bytes()
        })
        .collect();
    let macro_document = documents::vba_document(documents::VBA_MACRO_SOURCE);
    let samples: Vec<(&str, Vec<u8>)> = vec![
        ("vba-macro.doc", macro_document.clone()),
        (
            "vba-macro.zip",
            documents::zip_archive(&[("report.doc", macro_document.as_slice())]),
        ),
        (
            "vba-macro.eml",
            documents::email_attaching("report.doc", &macro_document),
        ),
        ("report-12-images.docx", report.clone()),
        (
            "archive-12-images.zip",
            documents::zip_archive(&image_parts),
        ),
        ("dataset-400000-rows.csv", dataset),
        (
            "report-12-images.eml",
            documents::email_attaching("report.docx", &report),
        ),
        ("report-nested.zip", nested),
        ("mail-only-member.docx", mail_only.clone()),
        ("mail-only-member.zip", mail_only_archive.clone()),
        (
            "mail-only-member-docx.eml",
            documents::email_attaching("mail-only.docx", &mail_only),
        ),
        (
            "mail-only-member-zip.eml",
            documents::email_attaching("mail-only.zip", &mail_only_archive),
        ),
        ("canary.docx", canary_document.clone()),
        (
            "canary-docx.eml",
            documents::email_attaching("canary.docx", &canary_document),
        ),
        (
            "attachments.pdf",
            documents::PdfBuilder::new("Bundle")
                .attachment("mail-only.docx", &mail_only)
                .attachment("canary.docx", &canary_document)
                .build(),
        ),
    ];
    for (name, bytes) in samples {
        fs::write(output.join(name), bytes).expect("writing a sample");
    }
}
