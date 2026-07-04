# File Drag-and-Drop Upload - Quick Start Guide

> [中文](../zh/file-upload-guide.md)

## Overview

You can now upload files by dragging them onto the chat area. The AI automatically reads the file content and analyzes it.

## Steps

### 1. Drag files
- Select one or more files in your file manager
- Drag them onto the chat area
- Release the mouse

### 2. Review attachments
- Files are shown as cards
- Each card shows the file name, size, and icon
- Image files show a thumbnail

### 3. Send the message
- Type your question or instruction
- Click send
- The AI sees the file content and responds

### 4. Open a file
- Click a file card to open it with the system default application

## Supported File Types

| Type | Extensions | Handling |
|------|------------|----------|
| Text | `.txt` | Read content directly |
| Markdown | `.md` | Read content directly |
| Image | `.png`, `.jpg`, `.jpeg` | OCR text recognition |

## Limits

- Maximum 10 MB per file
- Only the file types listed above are supported
- OCR accuracy depends on image quality

## Example Scenarios

### Scenario 1: Analyze a text file
1. Drop in `report.txt`
2. Enter: "Summarize the key points of this report"
3. The AI reads the file content and generates a summary

### Scenario 2: Recognize text in an image
1. Drop in `screenshot.png`
2. Enter: "Extract the text from the image"
3. The AI uses OCR to recognize the text in the image

### Scenario 3: Code review
1. Drop in `main.py`
2. Enter: "Check this code for issues"
3. The AI analyzes the code and gives suggestions

## Troubleshooting

### File cannot be uploaded
- Check whether the file type is supported
- Check whether the file size exceeds 10 MB
- Check the console logs for detailed errors

### OCR recognition fails
- Make sure the image is clear
- Make sure the text contrast is sufficient
- Try a higher-resolution image

### File fails to open
- Make sure the file still exists at its original location
- Make sure the system has a corresponding default application

## Technical Details

### File processing flow
1. User drags a file → `ChatWidget.dropEvent`
2. Parse the file → `FileParser.parse_file`
3. Create an attachment object → `Attachment`
4. Show the file card → `FileCardWidget`
5. Merge content when sending → `conversation_prompt_builder.merge_attachments_to_content`
6. AI receives the full context → generates a response

### Data storage
- Attachment information is stored in the `Message.attachments` list
- It includes the file path, name, type, size, and parsed content
- It is serialized together when the session is saved

### Security
- Only file content is read; the original file is not modified
- File paths are validated to prevent path traversal
- A file size limit prevents memory exhaustion
- A type allowlist prevents malicious files

## Roadmap

- [ ] Support PDF files
- [ ] Support Word documents
- [ ] Support Excel spreadsheets
- [ ] Add attachment preview and deletion
- [ ] Support pasting images
- [ ] Support uploading screenshots directly
