use std::io::{Cursor, Write};

use cfb::CompoundFile;
use lopdf::{
    Dictionary, Document, EncryptionState, EncryptionVersion, Object, Permissions, Stream,
    StringFormat, dictionary,
};
use zip::{CompressionMethod, ZipWriter, write::SimpleFileOptions};

pub const PNG_PIXEL: &[u8] = &[
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
    0x89, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0x60, 0x00, 0x02, 0x00,
    0x00, 0x05, 0x00, 0x01, 0xE9, 0xFA, 0xDC, 0xD8, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44,
    0xAE, 0x42, 0x60, 0x82,
];
pub const JPEG_HEADER: &[u8] = &[
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
    0x00, 0x01, 0x00, 0x00, 0xFF, 0xD9,
];
pub const ELF_HEADER: &[u8] = &[
    0x7F, 0x45, 0x4C, 0x46, 0x02, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x02, 0x00, 0x3E, 0x00, 0x01, 0x00, 0x00, 0x00, 0x78, 0x00, 0x40, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x40, 0x00, 0x38, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
];
pub const PORTABLE_EXECUTABLE_HEADER: &[u8] = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xFF\xFF\x00\x00This program cannot be run in DOS mode.";
pub const SHORTCUT_HEADER: &[u8] = &[
    0x4C, 0x00, 0x00, 0x00, 0x01, 0x14, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC0, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x46,
];

const WORD_MAIN: &str =
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml";
const WORD_MACRO_MAIN: &str = "application/vnd.ms-word.document.macroEnabled.main+xml";
const SHEET_MAIN: &str =
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml";
const PRESENTATION_MAIN: &str =
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml";
const WORKSHEET: &str = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml";
pub const MACRO_SHEET: &str = "application/vnd.ms-excel.macrosheet+xml";
pub const EXTERNAL_LINK: &str =
    "application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml";
const VBA_RELATIONSHIPS: &str = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="vbaProject.bin"/></Relationships>"#;
const PACKAGE_RELATIONSHIPS: &str = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="MAIN"/></Relationships>"#;

pub fn zip_archive(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    let options = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
    for (name, content) in entries {
        writer
            .start_file(*name, options)
            .expect("starting a member");
        writer.write_all(content).expect("writing a member");
    }
    writer.finish().expect("finishing the archive").into_inner()
}

pub fn text_with_canary(prefix: &str) -> Vec<u8> {
    format!("{prefix} {}\n", crate::canary::CANARY).into_bytes()
}

pub fn word_document(body_text: &str, extra_parts: &[(&str, &[u8])]) -> Vec<u8> {
    word_package(WORD_MAIN, &word_body(body_text), extra_parts)
}

pub fn macro_enabled_word_document() -> Vec<u8> {
    word_package_with(
        WORD_MACRO_MAIN,
        &word_body("Quarterly review"),
        &[r#"<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>"#],
        &[
            ("word/_rels/document.xml.rels", VBA_RELATIONSHIPS.as_bytes()),
            ("word/vbaProject.bin", b"Attribute VB_Name = \"Module1\""),
        ],
    )
}

pub fn word_body(text: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"#
    )
}

pub fn word_body_with_field(instruction_runs: &[&str]) -> String {
    let runs = instruction_runs
        .iter()
        .map(|run| format!("<w:r><w:instrText xml:space=\"preserve\">{run}</w:instrText></w:r>"))
        .collect::<Vec<_>>()
        .concat();
    format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>{runs}<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:body></w:document>"#
    )
}

pub fn word_package(main_content_type: &str, body: &str, extra_parts: &[(&str, &[u8])]) -> Vec<u8> {
    word_package_with(main_content_type, body, &[], extra_parts)
}

pub fn word_package_with(
    main_content_type: &str,
    body: &str,
    extra_types: &[&str],
    extra_parts: &[(&str, &[u8])],
) -> Vec<u8> {
    let extra_types = extra_types.concat();
    let content_types = format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>{extra_types}<Override PartName="/word/document.xml" ContentType="{main_content_type}"/></Types>"#
    );
    let relationships = PACKAGE_RELATIONSHIPS.replace("MAIN", "word/document.xml");
    let mut parts: Vec<(&str, &[u8])> = vec![
        ("[Content_Types].xml", content_types.as_bytes()),
        ("_rels/.rels", relationships.as_bytes()),
        ("word/document.xml", body.as_bytes()),
    ];
    parts.extend_from_slice(extra_parts);
    zip_archive(&parts)
}

pub fn workbook(extra_parts: &[(&str, &[u8])]) -> Vec<u8> {
    workbook_with(&[], extra_parts)
}

pub fn workbook_with(extra_overrides: &[(&str, &str)], extra_parts: &[(&str, &[u8])]) -> Vec<u8> {
    let overrides = extra_overrides
        .iter()
        .map(|(part, content_type)| {
            format!(r#"<Override PartName="{part}" ContentType="{content_type}"/>"#)
        })
        .collect::<Vec<_>>()
        .concat();
    let content_types = format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="{SHEET_MAIN}"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="{WORKSHEET}"/>{overrides}</Types>"#
    );
    let relationships = PACKAGE_RELATIONSHIPS.replace("MAIN", "xl/workbook.xml");
    let workbook = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Batches" sheetId="1"/></sheets></workbook>"#;
    let sheet = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>42</v></c><c r="B1"><f>A1*2</f></c></row></sheetData></worksheet>"#;
    let mut parts: Vec<(&str, &[u8])> = vec![
        ("[Content_Types].xml", content_types.as_bytes()),
        ("_rels/.rels", relationships.as_bytes()),
        ("xl/workbook.xml", workbook.as_bytes()),
        ("xl/worksheets/sheet1.xml", sheet.as_bytes()),
    ];
    parts.extend_from_slice(extra_parts);
    zip_archive(&parts)
}

pub fn presentation() -> Vec<u8> {
    let content_types = format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/presentation.xml" ContentType="{PRESENTATION_MAIN}"/></Types>"#
    );
    let relationships = PACKAGE_RELATIONSHIPS.replace("MAIN", "ppt/presentation.xml");
    let presentation = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>"#;
    zip_archive(&[
        ("[Content_Types].xml", content_types.as_bytes()),
        ("_rels/.rels", relationships.as_bytes()),
        ("ppt/presentation.xml", presentation.as_bytes()),
        ("ppt/media/image1.png", PNG_PIXEL),
    ])
}

pub fn external_relationship(relationship_type: &str, target: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{relationship_type}" Target="{target}" TargetMode="External"/></Relationships>"#
    )
}

pub fn compound_file(storages: &[&str], streams: &[(&str, &[u8])]) -> Vec<u8> {
    let mut document = CompoundFile::create(Cursor::new(Vec::new())).expect("a compound file");
    for storage in storages {
        document.create_storage_all(storage).expect("a storage");
    }
    for (path, content) in streams {
        document
            .create_stream(path)
            .expect("a stream")
            .write_all(content)
            .expect("writing a stream");
    }
    document.flush().expect("flushing the compound file");
    document.into_inner().into_inner()
}

pub fn compound_file_with_class(class_id: &str) -> Vec<u8> {
    let mut document = CompoundFile::create(Cursor::new(Vec::new())).expect("a compound file");
    let class_id = uuid::Uuid::parse_str(class_id).expect("a class id");
    document
        .set_storage_clsid("/", class_id)
        .expect("setting the class id");
    document
        .create_stream("/\u{5}SummaryInformation")
        .expect("a stream")
        .write_all(&[0; 64])
        .expect("writing a stream");
    document.flush().expect("flushing the compound file");
    document.into_inner().into_inner()
}

pub fn legacy_word_document(storages: &[&str], extra_streams: &[(&str, &[u8])]) -> Vec<u8> {
    let word_stream = [0xEC, 0xA5, 0xC1, 0x00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
    let mut streams: Vec<(&str, &[u8])> = vec![("/WordDocument", &word_stream)];
    streams.extend_from_slice(extra_streams);
    compound_file(storages, &streams)
}

pub fn biff_record(record_type: u16, body: &[u8]) -> Vec<u8> {
    let mut record = record_type.to_le_bytes().to_vec();
    record.extend_from_slice(
        &u16::try_from(body.len())
            .expect("short record")
            .to_le_bytes(),
    );
    record.extend_from_slice(body);
    record
}

pub fn legacy_workbook(storages: &[&str], sheet_type: u8) -> Vec<u8> {
    let mut workbook = biff_record(0x0809, &[0x00, 0x06, 0x05, 0x00, 0, 0, 0, 0]);
    workbook.extend(biff_record(
        0x0085,
        &[
            0, 0, 0, 0, 0, sheet_type, 6, 0, b'S', b'h', b'e', b'e', b't', b'1',
        ],
    ));
    workbook.extend(biff_record(0x000A, &[]));
    compound_file(storages, &[("/Workbook", &workbook)])
}

pub fn legacy_presentation_with_vba() -> Vec<u8> {
    let atom = [
        0x00, 0x00, 0x00, 0x04, 0x0C, 0x00, 0x00, 0x00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    ];
    let mut vba_container = vec![0x0F, 0x00, 0xFF, 0x03];
    vba_container.extend_from_slice(&u32::try_from(atom.len()).expect("short").to_le_bytes());
    vba_container.extend_from_slice(&atom);
    let mut document = vec![0x0F, 0x00, 0xE8, 0x03];
    document.extend_from_slice(
        &u32::try_from(vba_container.len())
            .expect("short")
            .to_le_bytes(),
    );
    document.extend_from_slice(&vba_container);
    compound_file(
        &[],
        &[
            ("/PowerPoint Document", &document),
            ("/Current User", &[0; 20]),
        ],
    )
}

pub fn password_protected_office_package() -> Vec<u8> {
    compound_file(
        &[],
        &[
            (
                "/EncryptionInfo",
                &[0x04, 0x00, 0x04, 0x00, 0x40, 0x00, 0x00, 0x00],
            ),
            ("/EncryptedPackage", &[0x5A; 4096]),
        ],
    )
}

pub fn native_package(label: &str, payload: &[u8]) -> Vec<u8> {
    let mut native = Vec::new();
    native.extend_from_slice(&0_u32.to_le_bytes());
    native.extend_from_slice(&2_u16.to_le_bytes());
    native.extend_from_slice(label.as_bytes());
    native.push(0);
    native.extend_from_slice(label.as_bytes());
    native.push(0);
    native.extend_from_slice(&0x0003_0000_u32.to_le_bytes());
    native.extend_from_slice(&u32::try_from(label.len() + 1).expect("short").to_le_bytes());
    native.extend_from_slice(label.as_bytes());
    native.push(0);
    native.extend_from_slice(&u32::try_from(payload.len()).expect("short").to_le_bytes());
    native.extend_from_slice(payload);
    native
}

pub struct PdfBuilder {
    document: Document,
    catalog: Dictionary,
    embedded_files: Vec<Object>,
}

impl PdfBuilder {
    pub fn new(text: &str) -> Self {
        let mut document = Document::with_version("1.7");
        let font = document.add_object(dictionary! {
            "Type" => "Font", "Subtype" => "Type1", "BaseFont" => "Helvetica",
        });
        let content = Stream::new(
            Dictionary::new(),
            format!("BT /F1 12 Tf 72 720 Td ({text}) Tj ET").into_bytes(),
        );
        let content = document.add_object(content);
        let pages = document.new_object_id();
        let page = document.add_object(dictionary! {
            "Type" => "Page",
            "Parent" => pages,
            "MediaBox" => vec![0.into(), 0.into(), 612.into(), 792.into()],
            "Contents" => content,
            "Resources" => dictionary! { "Font" => dictionary! { "F1" => font } },
        });
        document.objects.insert(
            pages,
            Object::Dictionary(dictionary! {
                "Type" => "Pages", "Kids" => vec![page.into()], "Count" => 1,
            }),
        );
        let catalog = dictionary! { "Type" => "Catalog", "Pages" => pages };
        Self {
            document,
            catalog,
            embedded_files: Vec::new(),
        }
    }

    pub fn open_action(mut self, action: Dictionary) -> Self {
        self.catalog.set("OpenAction", Object::Dictionary(action));
        self
    }

    pub fn attachment(self, name: &str, content: &[u8]) -> Self {
        self.attachment_described(name, content, dictionary! { "Type" => "EmbeddedFile" })
    }

    pub fn attachment_with_decode_parameters(self, name: &str, content: &[u8]) -> Self {
        self.attachment_described(
            name,
            content,
            dictionary! {
                "Type" => "EmbeddedFile",
                "DecodeParms" => dictionary! { "Predictor" => 1 },
            },
        )
    }

    fn attachment_described(mut self, name: &str, content: &[u8], description: Dictionary) -> Self {
        let mut stream = Stream::new(description, content.to_vec());
        stream.compress().expect("compressing the attachment");
        let stream = self.document.add_object(stream);
        let file_name = Object::String(name.as_bytes().to_vec(), StringFormat::Literal);
        let specification = self.document.add_object(dictionary! {
            "Type" => "Filespec",
            "F" => file_name.clone(),
            "UF" => file_name.clone(),
            "EF" => dictionary! { "F" => stream },
        });
        self.embedded_files.push(file_name);
        self.embedded_files.push(specification.into());
        self
    }

    pub fn build(self) -> Vec<u8> {
        self.finish(None)
    }

    pub fn build_encrypted(self, user_password: &str, owner_password: &str) -> Vec<u8> {
        self.finish(Some((user_password, owner_password)))
    }

    fn finish(mut self, passwords: Option<(&str, &str)>) -> Vec<u8> {
        if !self.embedded_files.is_empty() {
            self.catalog.set(
                "Names",
                dictionary! { "EmbeddedFiles" => dictionary! { "Names" => self.embedded_files } },
            );
        }
        let catalog = self.document.add_object(self.catalog);
        self.document.trailer.set("Root", catalog);
        let identifier = Object::String(b"metariki-fixture".to_vec(), StringFormat::Hexadecimal);
        self.document
            .trailer
            .set("ID", vec![identifier.clone(), identifier]);
        if let Some((user_password, owner_password)) = passwords {
            let version = EncryptionVersion::V2 {
                document: &self.document,
                owner_password,
                user_password,
                key_length: 128,
                permissions: Permissions::PRINTABLE,
            };
            let state = EncryptionState::try_from(version).expect("an encryption state");
            self.document
                .encrypt(&state)
                .expect("encrypting the fixture");
        }
        let mut bytes = Vec::new();
        self.document
            .save_to(&mut bytes)
            .expect("saving the fixture");
        bytes
    }
}

pub fn javascript_action() -> Dictionary {
    dictionary! {
        "S" => "JavaScript",
        "JS" => Object::String(b"app.alert('review');".to_vec(), StringFormat::Literal),
    }
}

pub fn launch_action() -> Dictionary {
    dictionary! {
        "S" => "Launch",
        "F" => Object::String(b"calc.exe".to_vec(), StringFormat::Literal),
    }
}

pub fn pseudo_random_bytes(length: usize) -> Vec<u8> {
    let mut state: u64 = 0x2545_f491_4f6c_dd1d;
    (0..length)
        .map(|_| {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            state.to_le_bytes()[0]
        })
        .collect()
}

pub fn pseudo_random_nibbles(length: usize) -> Vec<u8> {
    pseudo_random_bytes(length)
        .into_iter()
        .map(|byte| byte & 0x0F)
        .collect()
}

pub fn utf16_little_endian(text: &str) -> Vec<u8> {
    let mut bytes = vec![0xFF, 0xFE];
    for unit in text.encode_utf16() {
        bytes.extend_from_slice(&unit.to_le_bytes());
    }
    bytes
}

pub fn gzip(content: &[u8]) -> Vec<u8> {
    let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    encoder.write_all(content).expect("compressing in memory");
    encoder.finish().expect("compressing in memory")
}

pub fn gzip_members(members: &[&[u8]]) -> Vec<u8> {
    members.iter().flat_map(|member| gzip(member)).collect()
}

pub fn bzip2_members(members: &[&[u8]]) -> Vec<u8> {
    members
        .iter()
        .flat_map(|member| {
            let mut encoder =
                bzip2::write::BzEncoder::new(Vec::new(), bzip2::Compression::default());
            encoder.write_all(member).expect("compressing in memory");
            encoder.finish().expect("compressing in memory")
        })
        .collect()
}

pub fn xz_members(members: &[&[u8]]) -> Vec<u8> {
    members
        .iter()
        .flat_map(|member| {
            let mut writer =
                lzma_rust2::XzWriter::new(Vec::new(), lzma_rust2::XzOptions::with_preset(1))
                    .expect("an xz writer");
            writer.write_all(member).expect("compressing in memory");
            writer.finish().expect("compressing in memory")
        })
        .collect()
}

pub fn zstd_frames(frames: &[&[u8]]) -> Vec<u8> {
    frames
        .iter()
        .flat_map(|frame| {
            ruzstd::encoding::compress_to_vec(*frame, ruzstd::encoding::CompressionLevel::Fastest)
        })
        .collect()
}

const PATTERN_PERIOD_BYTES: usize = 1000;
const PATTERN_CHUNK_BYTES: usize = 1024 * 1024;

fn repeating_pattern_chunk() -> Vec<u8> {
    let period = pseudo_random_bytes(PATTERN_PERIOD_BYTES);
    period
        .iter()
        .copied()
        .cycle()
        .take(PATTERN_CHUNK_BYTES)
        .collect()
}

fn repeated_gzip_members(prefix: &[u8], chunks: u64, suffix: &[u8]) -> Vec<u8> {
    let chunk = gzip(&repeating_pattern_chunk());
    let mut bytes = gzip(prefix);
    for _ in 0..chunks {
        bytes.extend_from_slice(&chunk);
    }
    bytes.extend(gzip(suffix));
    bytes
}

pub fn gzip_of_repeating_pattern(megabytes: u64) -> Vec<u8> {
    repeated_gzip_members(b"", megabytes, b"")
}

pub fn tar_gz_of_repeating_pattern(megabytes: u64) -> Vec<u8> {
    let mut header = tar::Header::new_ustar();
    header.set_size(megabytes * PATTERN_CHUNK_BYTES as u64);
    header.set_mode(0o644);
    header.set_path("data.bin").expect("a tar path");
    header.set_cksum();
    repeated_gzip_members(header.as_bytes(), megabytes, &[0_u8; 1024])
}

pub fn tar_gz_declaring_size(declared: u64) -> Vec<u8> {
    gzip(&tar_declaring_size("data.bin", declared))
}

pub fn first_header_byte_of_seven_zip(archive: &[u8]) -> u8 {
    let offset = u64::from_le_bytes(
        archive
            .get(12..20)
            .and_then(|bytes| bytes.try_into().ok())
            .expect("a 7z start header"),
    );
    *archive
        .get(usize::try_from(offset).expect("fits") + 32)
        .expect("a 7z next header")
}

pub fn seven_zip(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut writer =
        sevenz_rust2::ArchiveWriter::new(Cursor::new(Vec::new())).expect("a 7z writer");
    for (name, content) in entries {
        writer
            .push_archive_entry(sevenz_rust2::ArchiveEntry::new_file(name), Some(*content))
            .expect("a 7z member");
    }
    writer
        .finish()
        .expect("finishing the 7z archive")
        .into_inner()
}

pub fn tar_archive(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut builder = tar::Builder::new(Vec::new());
    for (name, content) in entries {
        let mut header = tar::Header::new_ustar();
        header.set_size(u64::try_from(content.len()).expect("fits"));
        header.set_mode(0o644);
        header.set_cksum();
        builder
            .append_data(&mut header, name, *content)
            .expect("a tar member");
    }
    builder.into_inner().expect("finishing the tar archive")
}

const BASE64_LINE_CHARACTERS: usize = 76;

pub fn email_attaching(name: &str, attachment: &[u8]) -> Vec<u8> {
    let encoded = base64::Engine::encode(&base64::prelude::BASE64_STANDARD, attachment);
    let lines: Vec<&str> = encoded
        .as_bytes()
        .chunks(BASE64_LINE_CHARACTERS)
        .map(|line| std::str::from_utf8(line).expect("base64 is ASCII"))
        .collect();
    format!(
        "From: sender@example.com\r\nTo: recipient@example.com\r\nSubject: report\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=\"part\"\r\n\r\n--part\r\nContent-Type: text/plain\r\n\r\nSee attached.\r\n--part\r\nContent-Type: application/octet-stream\r\nContent-Disposition: attachment; filename=\"{name}\"\r\nContent-Transfer-Encoding: base64\r\n\r\n{}\r\n--part--\r\n",
        lines.join("\r\n")
    )
    .into_bytes()
}

const VBA_PROJECT_MAGIC: [u8; 2] = [0xCC, 0x61];
const VBA_STREAM_BYTES: usize = 4096;
const VBA_MODULE_NAME: &str = "Module1";
const VBA_PROJECT_STRING: &str = "*\\g";
const VBA_COMPRESSED_CONTAINER_SIGNATURE: u8 = 0x01;
const VBA_COMPRESSED_CHUNK_HEADER: u16 = 0xB000;
const VBA_LITERAL_TOKENS_PER_FLAG: usize = 8;
pub const VBA_MACRO_SOURCE: &[u8] =
    b"Attribute VB_Name = \"Module1\"\r\nSub AutoOpen()\r\n    MsgBox \"METARIKI-VBA-1234-PCRE\"\r\nEnd Sub\r\n";

fn utf16_little_endian_bytes(text: &str) -> Vec<u8> {
    text.encode_utf16().flat_map(u16::to_le_bytes).collect()
}

fn length_prefixed(bytes: &[u8]) -> Vec<u8> {
    let length = u16::try_from(bytes.len()).expect("a short VBA string");
    [length.to_le_bytes().as_slice(), bytes].concat()
}

pub fn vba_document(module_source: &[u8]) -> Vec<u8> {
    let source_offset = u32::try_from(VBA_STREAM_BYTES).expect("fits");
    let project = [
        VBA_PROJECT_MAGIC.as_slice(),
        &[0; 32],
        &length_prefixed(&utf16_little_endian_bytes(VBA_PROJECT_STRING)),
        &0_u16.to_le_bytes(),
        &[0; 10],
        &[0x00, 0x00, 0xFF, 0xFF],
        &[0xFF, 0xFF, 0xFF, 0xFF],
        &[0; 100],
        &1_u16.to_le_bytes(),
        &length_prefixed(&utf16_little_endian_bytes(VBA_MODULE_NAME)),
        &0_u16.to_le_bytes(),
        &0_u16.to_le_bytes(),
        &[0; 10],
        &0_u16.to_le_bytes(),
        &[0; 5],
        &source_offset.to_le_bytes(),
        &[0; 2],
    ]
    .concat();
    let mut project = project;
    project.resize(VBA_STREAM_BYTES, 0);
    let compressed: Vec<u8> = [
        vec![VBA_COMPRESSED_CONTAINER_SIGNATURE],
        VBA_COMPRESSED_CHUNK_HEADER.to_le_bytes().to_vec(),
    ]
    .into_iter()
    .chain(
        module_source
            .chunks(VBA_LITERAL_TOKENS_PER_FLAG)
            .map(|literals| [&[0_u8][..], literals].concat()),
    )
    .flatten()
    .collect();
    let module = [vec![0; VBA_STREAM_BYTES], compressed].concat();
    let mut document = CompoundFile::create_with_version(cfb::Version::V3, Cursor::new(Vec::new()))
        .expect("a compound file");
    for (name, content) in [
        ("/_VBA_PROJECT", &project),
        (&format!("/{VBA_MODULE_NAME}"), &module),
    ] {
        document
            .create_stream(name)
            .expect("a stream")
            .write_all(content)
            .expect("writing a stream");
    }
    document.flush().expect("flushing the compound file");
    document.into_inner().into_inner()
}

fn xz_vli(mut value: u64) -> Vec<u8> {
    let mut bytes = Vec::new();
    loop {
        let low = u8::try_from(value & 0x7F).expect("seven bits");
        value >>= 7;
        if value == 0 {
            bytes.push(low);
            return bytes;
        }
        bytes.push(low | 0x80);
    }
}

pub fn xz_declaring_unpacked_size(unpacked: u64) -> Vec<u8> {
    let unpadded = 24_u64;
    let mut bytes = b"\xfd7zXZ\x00".to_vec();
    bytes.extend([0, 4, 0, 0, 0, 0]);
    bytes.extend(vec![1_u8; 24]);
    let mut index = vec![0_u8];
    index.extend(xz_vli(1));
    index.extend(xz_vli(unpadded));
    index.extend(xz_vli(unpacked));
    while (index.len() + 4) % 4 != 0 {
        index.push(0);
    }
    index.extend([0_u8; 4]);
    let backward = u32::try_from(index.len() / 4 - 1).expect("fits");
    bytes.extend(&index);
    bytes.extend([0_u8; 4]);
    bytes.extend(backward.to_le_bytes());
    bytes.extend([0, 4]);
    bytes.extend(b"YZ");
    bytes
}

fn read_xz_vli(bytes: &[u8], position: &mut usize) -> (u64, usize) {
    let start = *position;
    let mut value = 0_u64;
    let mut shift = 0;
    loop {
        let byte = *bytes.get(*position).expect("a variable-length integer");
        *position += 1;
        value |= u64::from(byte & 0x7F) << shift;
        shift += 7;
        if byte & 0x80 == 0 {
            return (value, *position - start);
        }
    }
}

pub fn xz_with_lying_index(content: &[u8], claimed: u64) -> Vec<u8> {
    let mut bytes = xz_members(&[content]);
    let footer = bytes.len() - 12;
    let backward = u32::from_le_bytes(
        bytes
            .get(footer + 4..footer + 8)
            .and_then(|field| field.try_into().ok())
            .expect("a footer"),
    );
    let index_length = (usize::try_from(backward).expect("fits") + 1) * 4;
    let index_start = footer - index_length;
    let mut position = index_start + 1;
    let (records, _) = read_xz_vli(&bytes, &mut position);
    assert_eq!(records, 1, "one block");
    read_xz_vli(&bytes, &mut position);
    let uncompressed_start = position;
    let (_, width) = read_xz_vli(&bytes, &mut position);
    let replacement = xz_vli(claimed);
    assert_eq!(
        replacement.len(),
        width,
        "the claimed size takes the same width"
    );
    bytes
        .get_mut(uncompressed_start..uncompressed_start + width)
        .expect("the size field")
        .copy_from_slice(&replacement);
    let mut crc = flate2::Crc::new();
    crc.update(bytes.get(index_start..footer - 4).expect("the index"));
    bytes
        .get_mut(footer - 4..footer)
        .expect("the index checksum")
        .copy_from_slice(&crc.sum().to_le_bytes());
    bytes
}

pub fn tar_declaring_size(name: &str, size: u64) -> Vec<u8> {
    let mut header = tar::Header::new_ustar();
    header.set_size(size);
    header.set_mode(0o644);
    header.set_path(name).expect("a tar path");
    header.set_cksum();
    let mut bytes = header.as_bytes().to_vec();
    bytes.extend(vec![0_u8; 1024]);
    bytes
}

fn seven_zip_around(header: &[u8]) -> Vec<u8> {
    let mut bytes = vec![0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C, 0, 4, 0, 0, 0, 0];
    bytes.extend(0_u64.to_le_bytes());
    bytes.extend(u64::try_from(header.len()).expect("fits").to_le_bytes());
    bytes.extend([0_u8; 4]);
    bytes.extend_from_slice(header);
    bytes
}

fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = flate2::Crc::new();
    crc.update(bytes);
    crc.sum()
}

pub fn seven_zip_declaring_unpacked_size(unpacked: u64) -> Vec<u8> {
    let mut header = vec![
        0x01, 0x04, 0x06, 0x00, 0x01, 0x09, 0x05, 0x00, 0x07, 0x0B, 0x01, 0x00, 0x01, 0x01, 0x00,
        0x0C, 0xFF,
    ];
    header.extend(unpacked.to_le_bytes());
    header.extend([
        0x00, 0x08, 0x00, 0x00, 0x05, 0x01, 0x11, 0x05, 0x00, b'a', 0, 0, 0, 0x00, 0x00,
    ]);
    let mut start = 5_u64.to_le_bytes().to_vec();
    start.extend(u64::try_from(header.len()).expect("fits").to_le_bytes());
    start.extend(crc32(&header).to_le_bytes());
    let mut bytes = vec![0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C, 0, 4];
    bytes.extend(crc32(&start).to_le_bytes());
    bytes.extend(start);
    bytes.extend([0_u8; 5]);
    bytes.extend(header);
    bytes
}

pub fn seven_zip_with_compressed_header() -> Vec<u8> {
    seven_zip_around(&[0x17, 0x06, 0x00, 0x00])
}
