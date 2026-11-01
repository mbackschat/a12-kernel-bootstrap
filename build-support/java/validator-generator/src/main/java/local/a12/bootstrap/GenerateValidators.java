package local.a12.bootstrap;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import com.mgmtp.a12.kernel.md.model.api.services.IValidationCodeGeneratorConfig;
import com.mgmtp.a12.kernel.md.model.internal.service.ExternalDocumentModelService;
import com.mgmtp.a12.kernel.md.model.internal.service.utils.cli.ArchiveExtractor;
import com.mgmtp.a12.kernel.md.serializer.model.internal.service.DocumentModelSerializerImpl;
import com.mgmtp.a12.model.notification.RankedNotification;
import com.mgmtp.a12.model.notification.Severity;

/** Minimal build entry point for upstream's generator, avoiding the facade/metamodel cycle. */
public final class GenerateValidators {
    public static void main(String[] args) throws Exception {
        if (args.length != 4) throw new IllegalArgumentException("Expected model.json output-directory package-name variant");
        var config = new IValidationCodeGeneratorConfig() {
            public ProgrammingLanguage getProgrammingLanguage() { return ProgrammingLanguage.JAVA; }
            public Optional<String> getPackageName() { return Optional.of(args[2]); }
        };
        List<RankedNotification> notifications = new ArrayList<>();
        byte[] archive;
        try (var reader = Files.newBufferedReader(Path.of(args[0]), StandardCharsets.UTF_8)) {
            var model = new DocumentModelSerializerImpl().deserialize(reader);
            // ext1 removed the CLI's -vn option, while kernel consumers still
            // require variant-qualified generated identifiers. Supply that build
            // namespace through the model name; IDs, fields and rules stay intact.
            var info = ExternalDocumentModelService.getInternDocumentModel(model).getContent().getModelInfo();
            info.setName(args[3] + "_" + info.getName());
            archive = new ExternalDocumentModelService().generateValidationCode(model, config, null, notifications::add);
        }
        if (archive == null || notifications.stream().anyMatch(n -> n.getSeverity() == Severity.ERROR)) {
            throw new IllegalStateException("Metamodel generation failed: " + notifications);
        }
        new ArchiveExtractor(true).extractToDisk(archive, Path.of(args[1]), false);
    }
}
